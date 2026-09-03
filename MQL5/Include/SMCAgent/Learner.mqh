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
   bool              m_persist;      // false during optimisation: every pass starts clean
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
   int               m_pos;         // labels seen: objective reached
   int               m_neg;         // labels seen: invalidated
   //--- running spread of each feature (Welford). A feature that never
   //--- varies carries no information, yet gradient descent will happily
   //--- give it a large weight - at which point it acts as a second bias
   //--- term and drags every probability the same way. Damping the update
   //--- by the feature's own variability stops that.
   double            m_fmean[];
   double            m_fm2[];
   long              m_fn;

public:
                     COnlineLearner(void): m_n(0), m_bias(0.0), m_init_bias(0.0), m_lr(0.06), m_l2(0.010), m_updates(0),
                                           m_warmup_needed(25), m_file("smc_agent_model.csv"), m_persist(true), m_log(NULL),
                                           m_mem_cnt(0), m_mem_head(0), m_logloss(0.0), m_acc(0.0),
                                           m_scored(0), m_correct(0), m_pos(0), m_neg(0), m_fn(0) {}

   void              Init(const int n_features,const double &priors[],CLogger *log,
                          const string model_file,const int warmup_samples,const double init_bias=0.0,
                          const bool persist=true)
     {
      m_n=(int)MathMin(n_features,LRN_MAX_FEATURES);
      m_log=log;
      m_file=model_file;
      m_persist=persist;
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
      ArrayResize(m_fmean,m_n);
      ArrayResize(m_fm2,m_n);
      ArrayInitialize(m_fmean,0.0);
      ArrayInitialize(m_fm2,0.0);
      m_fn=0;
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
   double            PositiveRate(void) const
     { int t=m_pos+m_neg; return(t>0?(double)m_pos/(double)t:0.5); }
   //--- how much a feature actually varies, for the diagnostics log
   double            FeatureSd(const int i) const
     {
      if(i<0 || i>=m_n || m_fn<2) return(0.0);
      return(MathSqrt(m_fm2[i]/(double)(m_fn-1)));
     }

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
      //--- Class balancing. A stream that is 90% one label drags the bias
      //--- to that label and the model stops discriminating. Scaling each
      //--- update by the inverse frequency of its class keeps a skewed
      //--- stream from collapsing the model.
      if(y>0.5) m_pos++; else m_neg++;
      int    tot=m_pos+m_neg;
      double cls=1.0;
      if(tot>=20)
        {
         int own=(y>0.5?m_pos:m_neg);
         cls=SmcClamp((double)tot/(2.0*(double)MathMax(own,1)),0.40,2.50);
        }
      double sw=sample_weight*cls;

      //--- Welford update of each feature's spread
      m_fn++;
      for(int i=0;i<m_n && i<ArraySize(x);i++)
        {
         double d=x[i]-m_fmean[i];
         m_fmean[i]+=d/(double)m_fn;
         m_fm2[i]  +=d*(x[i]-m_fmean[i]);
        }

      double p=Probability(x);
      double err=p-y;
      double lr=m_lr/MathSqrt(1.0+(double)m_updates*0.05);
      for(int i=0;i<m_n && i<ArraySize(x);i++)
        {
         //--- damp the learning of a feature that barely moves; the pull
         //--- back towards its research prior is left at full strength, so
         //--- a dead feature decays to its prior instead of drifting
         double sd=(m_fn>1?MathSqrt(m_fm2[i]/(double)(m_fn-1)):1.0);
         double info=(m_fn>=30?SmcClamp(sd/0.15,0.0,1.0):1.0);
         double grad=err*x[i]*sw*info + m_l2*(m_w[i]-m_prior[i]);
         m_w[i]-=lr*grad;
         m_w[i]=SmcClamp(m_w[i],-4.0,4.0);
        }
      m_bias-=lr*(err*sw);
      //--- tighter clamp: a bias past this is the model giving up rather
      //--- than discriminating
      m_bias=SmcClamp(m_bias,-1.0,1.0);
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
      if(!m_persist) return(true);          // nothing to write, and nothing to corrupt
      int h=FileOpen(m_file,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON,SMC_FIELD_SEP);
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
      if(!m_persist) return(false);         // start from the priors, every pass
      int h=FileOpen(m_file,FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON,SMC_FIELD_SEP);
      if(h==INVALID_HANDLE) return(false);
      bool ok=false;
      m_mem_cnt=0; m_mem_head=0;
      while(!FileIsEnding(h))
        {
         string line=FileReadString(h);
         if(StringLen(line)<2) continue;
         string p[];
         int k=StringSplit(line,SMC_FIELD_SEP,p);
         if(k<2) k=StringSplit(line,'\t',p);      // tolerate a file written with the old default
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
      if(!ok) return(false);

      //--- Audit what was loaded. A label stream this one-sided means the
      //--- model has stopped discriminating, and loading it silently is
      //--- what kept a live build permanently out of the market.
      int pos=0;
      for(int s2=0;s2<m_mem_cnt;s2++) if(m_mem_y[s2]>0.5) pos++;
      m_pos=pos;
      m_neg=m_mem_cnt-pos;
      double rate=(m_mem_cnt>0?(double)pos/(double)m_mem_cnt:0.5);
      if(m_mem_cnt>=40 && (rate<0.15 || rate>0.85))
        {
         if(m_log!=NULL)
           {
            m_log.Err(StringFormat("Stored model is degenerate: only %.0f%% of %d labels reached their objective and the bias has saturated at %+.2f. It would price every setup near zero and never trade.",
                      rate*100.0,m_mem_cnt,m_bias));
            m_log.Err("Discarding it and restarting from the research priors. Delete the model file if this repeats.");
           }
         Reset();
         return(false);
        }
      if(m_log!=NULL)
         m_log.Info(StringFormat("Model restored: %d updates, %d memories, %.0f%% reached objective, acc=%.2f, bias %+.2f",
                    (int)m_updates,m_mem_cnt,rate*100.0,m_acc,m_bias));
      return(true);
     }

   void              Reset(void)
     {
      for(int i=0;i<m_n;i++) m_w[i]=m_prior[i];
      m_bias=m_init_bias; m_updates=0; m_mem_cnt=0; m_mem_head=0;
      m_scored=0; m_correct=0; m_acc=0.0; m_logloss=0.0;
      m_pos=0; m_neg=0; m_fn=0;
      ArrayInitialize(m_fmean,0.0);
      ArrayInitialize(m_fm2,0.0);
     }
  };

#endif // __SMC_LEARNER_MQH__
