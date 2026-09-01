//+------------------------------------------------------------------+
//|                                                      Learner.mqh |
//|                                                                  |
//|  Online (incremental) logistic regression over the confluence     |
//|  factor vector.                                                   |
//|                                                                  |
//|  Why this and not a deep net: the agent must learn from a handful |
//|  of trades per week, in real time, without look-ahead and without |
//|  an offline training pipeline. A regularised linear model updated |
//|  by SGD is the standard tool for that regime - it is stable with  |
//|  tiny samples, it degrades gracefully, and every weight stays     |
//|  readable on the dashboard, which is what "monitor live decision  |
//|  making" requires.                                                |
//|                                                                  |
//|  Two mechanisms keep it honest:                                   |
//|   1. WARM-UP: until it has observed enough resolved setups it does |
//|      not vote - the research priors drive the score.               |
//|   2. PRIOR ANCHORING: L2 pulls the weights towards the researched  |
//|      priors instead of towards zero, so a bad run of luck cannot   |
//|      erase the structural logic of the strategy.                   |
//+------------------------------------------------------------------+
#ifndef __SMC_LEARNER_MQH__
#define __SMC_LEARNER_MQH__

#include "Defs.mqh"
#include "Logger.mqh"

#define LRN_MAX_FEATURES 24
#define LRN_MEMORY       400      // replay memory of resolved observations

class COnlineLearner
  {
private:
   int               m_n;                    // feature count
   double            m_w[];                  // weights
   double            m_prior[];              // researched priors (anchor)
   double            m_bias;
   double            m_init_bias;
   double            m_lr;                   // base learning rate
   double            m_l2;                   // anchoring strength
   long              m_updates;
   int               m_warmup_needed;
   string            m_file;
   CLogger          *m_log;

   //--- replay memory ----------------------------------------------
   double            m_mem_x[];              // flattened [i*m_n + f]
   double            m_mem_y[];
   double            m_mem_w[];
   int               m_mem_cnt;
   int               m_mem_head;

   //--- running quality metrics ------------------------------------
   double            m_logloss;
   double            m_acc;
   int               m_scored;
   int               m_correct;

public:
                     COnlineLearner(void): m_n(0), m_bias(0.0), m_init_bias(0.0), m_lr(0.06), m_l2(0.010), m_updates(0),
                                           m_warmup_needed(25), m_file("smc_agent_model.csv"), m_log(NULL),
                                           m_mem_cnt(0), m_mem_head(0), m_logloss(0.0), m_acc(0.0),
                                           m_scored(0), m_correct(0) {}

   void              Init(const int n_features,const double &priors[],CLogger *log,
                          const string model_file,const int warmup_samples,const double init_bias=0.0)
     {
      m_n=(int)MathMin(n_features,LRN_MAX_FEATURES);
      m_log=log;
      m_file=model_file;
      m_warmup_needed=warmup_samples;
      ArrayResize(m_w,m_n);
      ArrayResize(m_prior,m_n);
      for(int i=0;i<m_n;i++)
        {
         double p=(i<ArraySize(priors)?priors[i]:0.0);
         m_prior[i]=p;
         m_w[i]=p;
        }
      m_bias=init_bias;
      m_init_bias=init_bias;
      ArrayResize(m_mem_x,LRN_MEMORY*m_n);
      ArrayResize(m_mem_y,LRN_MEMORY);
      ArrayResize(m_mem_w,LRN_MEMORY);
      ArrayInitialize(m_mem_x,0.0);
      ArrayInitialize(m_mem_y,0.0);
      ArrayInitialize(m_mem_w,0.0);
      m_mem_cnt=0; m_mem_head=0;
     }

   int               Features(void)  const { return(m_n); }
   long              Updates(void)   const { return(m_updates); }
   int               Samples(void)   const { return(m_mem_cnt); }
   bool              IsWarm(void)    const { return(m_updates>=(long)m_warmup_needed); }
   int               WarmupNeeded(void) const { return(m_warmup_needed); }
   double            Weight(const int i) const { return(i>=0 && i<m_n?m_w[i]:0.0); }
   double            Prior(const int i)  const { return(i>=0 && i<m_n?m_prior[i]:0.0); }
   double            Bias(void)      const { return(m_bias); }
   double            LogLoss(void)   const { return(m_logloss); }
   double            Accuracy(void)  const { return(m_acc); }

   //--- raw linear score (used for the "confluence score" display) ----
   double            Score(const double &x[])
     {
      double s=m_bias;
      for(int i=0;i<m_n && i<ArraySize(x);i++) s+=m_w[i]*x[i];
      return(s);
     }

   double            Probability(const double &x[]) { return(SmcSigmoid(Score(x))); }

   //--- probability using the untouched research priors ---------------
   double            PriorProbability(const double &x[])
     {
      double s=m_init_bias;
      for(int i=0;i<m_n && i<ArraySize(x);i++) s+=m_prior[i]*x[i];
      return(SmcSigmoid(s));
     }

   //--- blended probability: priors dominate during warm-up -----------
   double            BlendedProbability(const double &x[])
     {
      double pl=Probability(x);
      double pp=PriorProbability(x);
      double k=SmcClamp((double)m_updates/(double)MathMax(m_warmup_needed,1),0.0,1.0);
      return(pp*(1.0-k)+pl*k);
     }

   //--- one supervised update: y = 1 (target reached) / 0 (stopped) ---
   void              Learn(const double &x[],const double y,const double sample_weight=1.0)
     {
      if(m_n<=0) return;
      double p=Probability(x);
      double err=p-y;
      double lr=m_lr/MathSqrt(1.0+(double)m_updates*0.05);
      for(int i=0;i<m_n && i<ArraySize(x);i++)
        {
         double grad=err*x[i]*sample_weight + m_l2*(m_w[i]-m_prior[i]);
         m_w[i]-=lr*grad;
         m_w[i]=SmcClamp(m_w[i],-4.0,4.0);
        }
      m_bias-=lr*(err*sample_weight);
      m_bias=SmcClamp(m_bias,-2.0,2.0);
      m_updates++;

      //--- metrics
      double eps=1e-6;
      double ll=-(y*MathLog(MathMax(p,eps))+(1.0-y)*MathLog(MathMax(1.0-p,eps)));
      m_logloss=(m_scored==0?ll:m_logloss*0.9+ll*0.1);
      m_scored++;
      if((p>=0.5 && y>0.5) || (p<0.5 && y<0.5)) m_correct++;
      m_acc=SmcSafeDiv((double)m_correct,(double)m_scored,0.0);

      Remember(x,y,sample_weight);
     }

   //--- store into the replay memory ----------------------------------
   void              Remember(const double &x[],const double y,const double w)
     {
      int slot=m_mem_head;
      for(int i=0;i<m_n;i++) m_mem_x[slot*m_n+i]=(i<ArraySize(x)?x[i]:0.0);
      m_mem_y[slot]=y;
      m_mem_w[slot]=w;
      m_mem_head=(m_mem_head+1)%LRN_MEMORY;
      if(m_mem_cnt<LRN_MEMORY) m_mem_cnt++;
     }

   //--- a few passes over the memory: cheap consolidation -------------
   void              Replay(const int epochs=2)
     {
      if(m_mem_cnt<10) return;
      double xb[];
      ArrayResize(xb,m_n);
      for(int e=0;e<epochs;e++)
         for(int s=0;s<m_mem_cnt;s++)
           {
            for(int i=0;i<m_n;i++) xb[i]=m_mem_x[s*m_n+i];
            double p=Probability(xb);
            double err=p-m_mem_y[s];
            double lr=m_lr*0.35/MathSqrt(1.0+(double)m_updates*0.05);
            for(int i=0;i<m_n;i++)
              {
               double grad=err*xb[i]*m_mem_w[s]+m_l2*(m_w[i]-m_prior[i]);
               m_w[i]=SmcClamp(m_w[i]-lr*grad,-4.0,4.0);
              }
            m_bias=SmcClamp(m_bias-lr*err*m_mem_w[s],-2.0,2.0);
           }
     }

   //--- persistence ---------------------------------------------------
   bool              Save(void)
     {
      int h=FileOpen(m_file,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(h==INVALID_HANDLE) return(false);
      FileWrite(h,"SMC_AGENT_MODEL",SMC_AGENT_VERSION,m_n,DoubleToString(m_bias,8),(string)m_updates,
                DoubleToString(m_acc,6),DoubleToString(m_logloss,6));
      for(int i=0;i<m_n;i++) FileWrite(h,"W",i,DoubleToString(m_w[i],8),DoubleToString(m_prior[i],8));
      for(int s=0;s<m_mem_cnt;s++)
        {
         string row="";
         for(int i=0;i<m_n;i++) row+=DoubleToString(m_mem_x[s*m_n+i],6)+(i<m_n-1?",":"");
         FileWrite(h,"S",DoubleToString(m_mem_y[s],3),DoubleToString(m_mem_w[s],3),row);
        }
      FileClose(h);
      return(true);
     }

   bool              Load(void)
     {
      int h=FileOpen(m_file,FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(h==INVALID_HANDLE) return(false);
      bool ok=false;
      m_mem_cnt=0; m_mem_head=0;
      while(!FileIsEnding(h))
        {
         string line=FileReadString(h);
         if(StringLen(line)<2) continue;
         string p[];
         int k=StringSplit(line,'\t',p);
         if(k<2) k=StringSplit(line,';',p);
         if(k<2) continue;
         if(p[0]=="SMC_AGENT_MODEL" && k>=5)
           {
            int n=(int)StringToInteger(p[2]);
            if(n!=m_n) { FileClose(h); if(m_log!=NULL) m_log.Warn("Model file feature count mismatch - starting from priors"); return(false); }
            m_bias=StringToDouble(p[3]);
            m_updates=(long)StringToInteger(p[4]);
            if(k>=6) m_acc=StringToDouble(p[5]);
            if(k>=7) m_logloss=StringToDouble(p[6]);
            ok=true;
           }
         else if(p[0]=="W" && k>=3)
           {
            int i=(int)StringToInteger(p[1]);
            if(i>=0 && i<m_n) m_w[i]=StringToDouble(p[2]);
           }
         else if(p[0]=="S" && k>=4)
           {
            string xs[];
            int kk=StringSplit(p[3],',',xs);
            if(kk<m_n) continue;
            double xb[];
            ArrayResize(xb,m_n);
            for(int i=0;i<m_n;i++) xb[i]=StringToDouble(xs[i]);
            Remember(xb,StringToDouble(p[1]),StringToDouble(p[2]));
           }
        }
      FileClose(h);
      if(ok && m_log!=NULL)
         m_log.Info(StringFormat("Model restored: %d updates, %d memories, acc=%.2f",(int)m_updates,m_mem_cnt,m_acc));
      return(ok);
     }

   void              Reset(void)
     {
      for(int i=0;i<m_n;i++) m_w[i]=m_prior[i];
      m_bias=m_init_bias; m_updates=0; m_mem_cnt=0; m_mem_head=0;
      m_scored=0; m_correct=0; m_acc=0.0; m_logloss=0.0;
     }
  };

#endif // __SMC_LEARNER_MQH__
