//+------------------------------------------------------------------+
//|                                                 SMC_AI_Agent.mq5 |
//|                                                                  |
//|   XAUUSD Smart Money Concepts agent for FTMO 2-step accounts.    |
//|                                                                  |
//|   This is not a parameter driven expert advisor. There is no     |
//|   moving average period to optimise, no RSI level, no fixed pip  |
//|   distance. On every bar close the agent:                        |
//|                                                                  |
//|     1. re-reads the raw candles of three timeframes and          |
//|        calibrates itself to the volatility, rhythm and           |
//|        participation that are visible right now;                 |
//|     2. rebuilds the full Smart Money picture (market structure,  |
//|        BOS / CHoCH, inducement, order blocks, imbalances, equal  |
//|        highs and lows, session and daily liquidity, premium and  |
//|        discount);                                                |
//|     3. proposes a directional hypothesis from one of three       |
//|        researched playbooks;                                     |
//|     4. measures 17 confluence factors for that hypothesis and    |
//|        converts them into a probability with an online model     |
//|        that keeps learning from every resolved setup;            |
//|     5. sizes and manages the trade inside a layered FTMO risk    |
//|        envelope that cannot lose 5% in a day;                    |
//|     6. draws everything it saw and prints why it acted.          |
//|                                                                  |
//|   Research behind the playbooks and the factor priors:           |
//|   see docs/RESEARCH.md and docs/STRATEGY.md.                     |
//+------------------------------------------------------------------+
#property copyright "SMC AI Agent"
#property link      "https://github.com/basie8/ai-job-hunt-privacy"
#property version   "1.00"
#property description "XAUUSD Smart Money Concepts agent - live chart reading, adaptive confluence, FTMO 2-step risk envelope"

#include <SMCAgent/Defs.mqh>
#include <SMCAgent/TimeZones.mqh>
#include <SMCAgent/Logger.mqh>
#include <SMCAgent/MarketState.mqh>
#include <SMCAgent/SmcEngine.mqh>
#include <SMCAgent/NewsFilter.mqh>
#include <SMCAgent/Learner.mqh>
#include <SMCAgent/Confluence.mqh>
#include <SMCAgent/RiskManager.mqh>
#include <SMCAgent/TradeManager.mqh>
#include <SMCAgent/Visuals.mqh>

//+------------------------------------------------------------------+
//| Inputs - account and compliance only, no technical parameters    |
//+------------------------------------------------------------------+
input group "=== FTMO 2-step compliance ==="
input double InpInitialCapital   = 0.0;    // Initial simulated capital (0 = detect from the account)
input int    InpPhase            = 1;      // Phase: 1 = Challenge (10%), 2 = Verification (5%)
input double InpTargetPct        = 0.0;    // Profit target % (0 = 10 in phase 1 / 5 in phase 2)
input double InpDailyLossPct     = 5.0;    // FTMO maximum daily loss %
input double InpMaxLossPct       = 10.0;   // FTMO maximum overall loss %
input double InpSoftDailyPct     = 2.5;    // Stop trading for the day at this daily loss %
input double InpHardDailyPct     = 3.5;    // Flatten everything at this daily loss %
input double InpSoftMaxPct       = 7.0;    // Protective overall drawdown %
input double InpBaseRiskPct      = 0.5;    // Base risk per trade % of initial capital
input int    InpDailyResetHour   = 0;      // Server hour of the FTMO daily reset (midnight CE(S)T)
input int    InpGmtOffsetHours   = 99;     // Broker GMT offset in hours (99 = detect automatically)
input int    InpMinTradingDays   = 4;      // Minimum trading days required by the phase

input group "=== Agent behaviour ==="
input int    InpMaxPositions     = 1;      // Maximum simultaneous positions
input double InpMinProbability   = 0.62;   // Acceptance probability at full selectivity
input double InpMinProbFloor     = 0.55;   // Never accept below this probability
input int    InpTargetTradesWeek = 2;      // Minimum trades per week the agent aims for
input int    InpWarmupSamples    = 25;     // Resolved setups observed before the model votes
input bool   InpVirtualLearning  = true;   // Keep learning from setups that were not traded
input bool   InpResetModel       = false;  // Discard the stored model on start

input group "=== Trade management ==="
input double InpPartialAtR       = 1.00;   // Take partial profit at this R multiple
input double InpPartialPercent   = 50.0;   // Percent of the position closed at that point
input double InpBreakEvenAtR     = 1.00;   // Move the stop to break even at this R
input double InpTrailAfterR      = 1.50;   // Start structural trailing after this R
input int    InpTimeStopBars     = 0;      // Give up after N bars without expansion (0 = adaptive)
input int    InpSlippagePoints   = 40;     // Maximum deviation in points

input group "=== News ==="
input bool   InpUseNews          = true;   // Use the economic calendar
input int    InpNewsMinutesBefore= 15;     // Block new entries N minutes before a release
input int    InpNewsMinutesAfter = 10;     // Block new entries N minutes after a release
input int    InpNewsImportance   = 3;      // 1 = low, 2 = moderate, 3 = high impact only
input bool   InpFlattenBeforeNews= true;   // Close positions before a high impact release
input string InpNewsCsv          = "smc_news.csv"; // Fallback calendar (common files folder)

input group "=== Visuals and logging ==="
input bool   InpShowChart        = true;   // Draw the SMC map on the chart
input bool   InpShowPanel        = true;   // Draw the live decision panel
input int    InpPanelX           = 8;      // Panel X
input int    InpPanelY           = 22;     // Panel Y
input int    InpLogLevel         = 3;      // 0 err 1 warn 2 info 3 decisions 4 debug
input bool   InpLogToFile        = false;  // Also write the decision log to a file
input long   InpMagic            = 20260901;// Magic number

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
CLogger        g_log;
CMarketState   g_ms;
CSmcEngine     g_eng_e;
CSmcEngine     g_eng_m;
CSmcEngine     g_eng_h;
CNewsFilter    g_news;
COnlineLearner g_model;
CConfluence    g_conf;
CRiskManager   g_risk;
CTradeExec     g_exec;
CTradeJournal  g_journal;
CVirtualBook   g_vbook;
CVisuals       g_vis;

int            g_size_skips    = 0;      // consecutive setups skipped for lot size
datetime       g_last_bar      = 0;
datetime       g_last_signal   = 0;
string         g_last_action   = "starting up";
int            g_gmt           = 0;
double         g_threshold     = 0.62;
SSignal        g_sig;
bool           g_ready         = false;

//--- research based priors for the 17 confluence factors ------------
//--- (see docs/RESEARCH.md for the source of each number)
double         g_priors[F_COUNT];

//+------------------------------------------------------------------+
void SetPriors()
  {
   g_priors[F_HTF_BIAS]     = 0.26;   // higher timeframe narrative alignment
   g_priors[F_MID_BIAS]     = 0.18;   // intermediate timeframe agreement
   g_priors[F_STRUCTURE]    = 0.30;   // CHoCH / BOS confirmation on the entry chart
   g_priors[F_SWEEP]        = 0.28;   // quality and freshness of the liquidity raid
   g_priors[F_OB_QUALITY]   = 0.22;   // order block quality
   g_priors[F_FVG_CONF]     = 0.16;   // imbalance stacked with the order block
   g_priors[F_PREM_DISC]    = 0.20;   // discount for longs / premium for shorts
   g_priors[F_DISPLACEMENT] = 0.18;   // energy of the confirming leg
   g_priors[F_SESSION]      = 0.12;   // killzone timing
   g_priors[F_VOLATILITY]   = 0.10;   // volatility regime
   g_priors[F_EXECUTION]    = 0.10;   // spread against the planned stop
   g_priors[F_RR]           = 0.16;   // reward to risk of the mapped objective
   g_priors[F_KEYLEVEL]     = 0.14;   // daily / weekly / session level confluence
   g_priors[F_CANDLE]       = 0.14;   // confirmation candle quality
   g_priors[F_VOLUME]       = 0.08;   // participation on the confirmation
   g_priors[F_NEWS]         = 0.16;   // macro context
   g_priors[F_INDUCEMENT]   = 0.20;   // has the pullback liquidity in front of the zone been run
  }

//+------------------------------------------------------------------+
//| Broker clock alignment.                                          |
//|                                                                  |
//| Every timestamp inside the agent is server time. The MT5 economic|
//| calendar publishes its events in GMT, so the offset below is the |
//| single conversion used for news, killzones and session scoring.  |
//| It is re-detected every day, which is what makes a broker        |
//| daylight-saving switch self-correcting.                          |
//+------------------------------------------------------------------+
int DetectGmtOffset()
  {
   if(InpGmtOffsetHours>=-14 && InpGmtOffsetHours<=14) return(InpGmtOffsetHours);
   int auto_off=SmcServerGmtOffsetHours();
   if(auto_off==99)
     {
      //--- clock unusable (bad terminal timezone, or the tester): keep the
      //--- last good value rather than silently shifting every event
      g_log.Warn("Server/GMT offset could not be established - keeping the previous value. Set InpGmtOffsetHours manually if this repeats.");
      return(g_gmt);
     }
   return(auto_off);
  }

//+------------------------------------------------------------------+
//| Re-detect the offset and push it everywhere that converts time    |
//+------------------------------------------------------------------+
void SyncBrokerClock(const bool announce=false)
  {
   int off=DetectGmtOffset();
   if(off==g_gmt && !announce) return;
   if(off!=g_gmt)
     {
      int jump=(int)MathAbs(off-g_gmt);
      g_log.Warn(StringFormat("Broker clock re-aligned: GMT%+d -> GMT%+d (server %s / GMT %s)",
                 g_gmt,off,TimeToString(SmcNow(),TIME_DATE|TIME_MINUTES),
                 TimeToString(TimeGMT(),TIME_DATE|TIME_MINUTES)));
      //--- a daylight saving switch moves the offset by exactly one hour.
      //--- Anything larger is a machine clock or timezone fault, not a
      //--- seasonal change, and it would silently move every news window.
      if(jump>1)
         g_log.Err(StringFormat("Offset jumped by %d hours - that is not a daylight saving change. Check this machine's clock and timezone, and pin InpGmtOffsetHours if the terminal cannot be trusted.",jump));
     }
   g_gmt=off;
   g_conf.SetGmtOffset(g_gmt);
   if(InpUseNews) g_news.SetGmtOffset(g_gmt);
   if(announce) AnnounceClocks();
  }

//+------------------------------------------------------------------+
//| Print every frame of reference at once, and translate the session |
//| schedule into the trader's own day. The decisions themselves are  |
//| anchored to the exchanges and are identical in every location -   |
//| this is so the operator can see when the agent will be awake.     |
//+------------------------------------------------------------------+
void AnnounceClocks()
  {
   datetime srv=SmcNow();
   datetime utc=SmcServerToUtc(srv,g_gmt);
   int      pc =SmcPcGmtOffsetHours();

   g_log.Info(StringFormat("Clock | server %s (GMT%+d) | GMT %s | this PC %s (%s) | %s %s (%s) | %s %s (%s)",
              TimeToString(srv,TIME_MINUTES),g_gmt,
              TimeToString(TimeGMT(),TIME_MINUTES),
              TimeToString(TimeLocal(),TIME_MINUTES),
              (pc==99?"offset unknown":StringFormat("GMT%+d",pc)),
              SmcZoneName(TZ_LONDON),SmcHm(SmcZoneHourF(TZ_LONDON,utc)),SmcZoneAbbr(TZ_LONDON,utc),
              SmcZoneName(TZ_NY),SmcHm(SmcZoneHourF(TZ_NY,utc)),SmcZoneAbbr(TZ_NY,utc)));

   //--- the two killzones, expressed in server time and in the operator's time
   datetime ldn_day=SmcZoneDayStart(TZ_LONDON,utc);
   datetime ny_day =SmcZoneDayStart(TZ_NY,utc);
   double sf,st,pf,pt;
   SmcZoneWindowElsewhere(TZ_LONDON,ldn_day,7.0,10.0,g_gmt,sf,st,pf,pt);
   g_log.Info(StringFormat("Session | London killzone 07:00-10:00 London local = %s-%s server = %s-%s on this PC",
              SmcHm(sf),SmcHm(st),SmcHm(pf),SmcHm(pt)));
   SmcZoneWindowElsewhere(TZ_NY,ny_day,8.0,11.0,g_gmt,sf,st,pf,pt);
   g_log.Info(StringFormat("Session | New York killzone 08:00-11:00 New York local = %s-%s server = %s-%s on this PC",
              SmcHm(sf),SmcHm(st),SmcHm(pf),SmcHm(pt)));

   if(pc==99)
      g_log.Warn("This machine's timezone could not be read. Session decisions are unaffected (they are anchored to the exchanges), but verify the broker offset above and pin InpGmtOffsetHours if it looks wrong.");
  }

//+------------------------------------------------------------------+
//| Phase capital.                                                    |
//|                                                                  |
//| Every FTMO limit is a percentage of the capital the phase STARTED |
//| with, not of the balance right now. Using the current balance is  |
//| only safe on day one: attach the agent when the account is        |
//| already 3% down and "10% of the current balance" sits well below  |
//| the level the firm actually closes the account at.                |
//|                                                                  |
//| So the opening deposit is read from the account's own history -   |
//| the first balance operation - and the live balance is used only   |
//| as a last resort, with a warning when that is demonstrably unsafe.|
//+------------------------------------------------------------------+
double DetectInitialCapital(string &source)
  {
   if(InpInitialCapital>0.0)
     {
      source="set manually";
      return(InpInitialCapital);
     }

   double deposit=0.0;
   datetime first=0;
   int closed_trades=0;
   if(HistorySelect(0,SmcNow()))
     {
      int deals=HistoryDealsTotal();
      for(int i=0;i<deals;i++)
        {
         ulong d=HistoryDealGetTicket(i);
         if(d==0) continue;
         long type=HistoryDealGetInteger(d,DEAL_TYPE);
         if(type==DEAL_TYPE_BALANCE)
           {
            double v=HistoryDealGetDouble(d,DEAL_PROFIT);
            if(v<=0.0) continue;                                  // deposits, not withdrawals
            datetime t=(datetime)HistoryDealGetInteger(d,DEAL_TIME);
            if(first==0 || t<first) { first=t; deposit=v; }
           }
         else if(type==DEAL_TYPE_BUY || type==DEAL_TYPE_SELL)
           {
            if(HistoryDealGetInteger(d,DEAL_ENTRY)==DEAL_ENTRY_OUT) closed_trades++;
           }
        }
     }

   if(deposit>0.0)
     {
      source=StringFormat("detected from the opening deposit of %s",TimeToString(first,TIME_DATE));
      return(deposit);
     }

   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   source="fallback: current balance";
   if(closed_trades>0)
      g_log.Warn(StringFormat("No opening deposit found in history, but this account already has %d closed trades. Falling back to the current balance %.2f as the phase capital - if the phase is already under way this makes every FTMO floor WRONG. Set InpInitialCapital to the real starting capital.",
                 closed_trades,bal));
   else
      g_log.Info(StringFormat("No balance operation in history; using the current balance %.2f as the phase capital.",bal));
   return(bal);
  }

//+------------------------------------------------------------------+
//| Can this account actually trade this instrument at this risk?     |
//|                                                                  |
//| Everything monetary scales with the phase capital - floors,       |
//| targets, the per-trade budget and therefore the lot size. What    |
//| does NOT scale is the stop: it is placed where the idea is        |
//| invalidated, from structure and live volatility, and is the same  |
//| distance on a 1,000 account as on a 100,000 one. The broker's     |
//| minimum lot then puts a hard floor under the smallest risk that   |
//| can be expressed. On a small account that floor can exceed the    |
//| risk budget, in which case every setup is skipped - correctly,    |
//| but silently. This says so out loud, once, at start-up.           |
//+------------------------------------------------------------------+
void ReportSizingFeasibility()
  {
   double unit=g_eng_e.Unit();
   if(unit<=0.0) { g_log.Warn("Sizing check skipped: volatility not calibrated yet."); return; }

   double typical=unit*1.85;                 // representative structural stop
   double deepest=unit*4.50;                 // the widest the agent will accept
   double vmin=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double budget=g_risk.Initial()*g_risk.BaseRiskPct()/100.0;

   //--- a broker that does not report tick value or size cannot be sized
   //--- against at all; say that, rather than printing zeros
   if(g_risk.LossPerLot(typical)<=0.0)
     {
      g_log.Err(StringFormat("Sizing | %s does not report a usable tick size/value (tick size %.5f, tick value %.5f). No position can be sized and every setup will be skipped. Check the symbol specification.",
                _Symbol,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE),
                SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE)));
      return;
     }

   double want=0,minrisk=0,minpct=0,needpct=0;
   bool ok=g_risk.SizingFeasible(typical,want,minrisk,minpct,needpct);

   g_log.Info(StringFormat("Sizing | phase capital %.2f, risk budget %.2f (%.2f%%). Typical stop %.2f, deepest accepted %.2f.",
              g_risk.Initial(),budget,g_risk.BaseRiskPct(),typical,deepest));
   g_log.Info(StringFormat("Sizing | one minimum lot (%.2f) risks %.2f on that stop = %.2f%% of phase capital. Agent wants %.4f lots.",
              vmin,minrisk,minpct,want));

   if(!ok)
     {
      double need_capital=(vmin>0.0?minrisk/(g_risk.BaseRiskPct()/100.0):0.0);
      g_log.Err(StringFormat("Sizing | NOT TRADEABLE at this risk: the smallest position the broker allows risks %.2f%% but the budget is %.2f%%. Every setup will be skipped.",
                minpct,g_risk.BaseRiskPct()));
      g_log.Err(StringFormat("Sizing | Fix it one of two ways: raise InpBaseRiskPct to at least %.2f%%, or run this strategy on at least %.0f of capital (about %.0f for usable granularity).",
                needpct,need_capital,need_capital*2.0));
      g_log.Err("Sizing | The agent will NOT raise your risk on its own - that decision is yours.");
     }
   else
     {
      double granularity=(vmin>0.0?want/vmin:0.0);
      if(granularity<2.0)
         g_log.Warn(StringFormat("Sizing | workable but coarse: only %.1f lot steps fit inside the risk budget, so real risk per trade will sit noticeably below target. %.0f of capital would give comfortable granularity.",
                    granularity,g_risk.Initial()*2.0/MathMax(granularity,0.01)));
      else
         g_log.Info(StringFormat("Sizing | comfortable: %.1f lot steps fit inside the risk budget.",granularity));
     }
  }

//+------------------------------------------------------------------+
double PhaseTarget()
  {
   if(InpTargetPct>0.0) return(InpTargetPct);
   return(InpPhase>=2?5.0:10.0);
  }

//+------------------------------------------------------------------+
//| Frequency governor: keeps the agent selective, but makes sure it |
//| still delivers the required number of setups per week.           |
//+------------------------------------------------------------------+
double AcceptanceThreshold()
  {
   double thr=InpMinProbability;

   //--- how far into the trading week are we (Monday 00:00 -> Friday 21:00)
   datetime now=SmcNow();
   datetime ws=SmcWeekStart(now);
   double   span=4.0*86400.0+21.0*3600.0;
   double   elapsed=SmcClamp(((double)now-(double)ws)/span,0.0,1.0);

   double expected=InpTargetTradesWeek*elapsed;
   double shortfall=expected-(double)g_risk.WeekTrades();
   if(shortfall>0.0) thr-=SmcClamp(shortfall*0.035,0.0,0.10);

   //--- tighten up after losses and when the daily budget is thin
   thr+=SmcClamp(g_risk.LossStreak()*0.02,0.0,0.06);
   double budget_ratio=SmcSafeDiv(g_risk.RemainingDailyBudget(),g_risk.Initial()*InpSoftDailyPct/100.0,1.0);
   if(budget_ratio<0.5) thr+=0.03;

   //--- protect a nearly finished phase
   if(g_risk.TargetProgress()>0.85) thr+=0.04;

   return(SmcClamp(thr,InpMinProbFloor,0.90));
  }

//+------------------------------------------------------------------+
string NewsLine()
  {
   if(!InpUseNews) return("calendar disabled");
   string s=g_news.Describe(SmcNow(),InpNewsImportance);
   if(!g_news.Available()) s="calendar unavailable - "+s;
   else if(g_news.UsingCsv()) s="[csv] "+s;
   return(StringFormat("%s  [GMT%+d]",s,g_gmt));
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   g_log.SetLevel(InpLogLevel);
   if(InpLogToFile) g_log.OpenFile("smc_agent_log.txt");

   g_log.Info(StringFormat("%s v%s starting on %s %s",SMC_AGENT_NAME,SMC_AGENT_VERSION,
              _Symbol,EnumToString((ENUM_TIMEFRAMES)Period())));

   string sym=_Symbol;
   StringToUpper(sym);
   if(StringFind(sym,"XAU")<0 && StringFind(sym,"GOLD")<0)
      g_log.Warn("This agent was researched and calibrated for XAUUSD. It will still read any chart, but the news currency map and session profile assume gold.");

   //--- the daylight saving rules are computed, not fetched: prove them
   //--- against known transition dates before anything else runs
   string tz_report="";
   if(SmcTimezoneSelfTest(tz_report)) g_log.Info("Timezone self test: "+tz_report);
   else
     {
      g_log.Err("Timezone self test FAILED: "+tz_report);
      g_log.Err("Session windows cannot be trusted - refusing to start. Update TimeZones.mqh or pin InpGmtOffsetHours and disable session scoring.");
      return(INIT_FAILED);
     }

   g_gmt=DetectGmtOffset();
   g_log.Info(StringFormat("Server time is GMT%+d (%s) - killzones, the calendar and the daily reset are mapped to it",
              g_gmt,(InpGmtOffsetHours>=-14 && InpGmtOffsetHours<=14?"set manually":"auto-detected")));

   if(!g_ms.Init(_Symbol,(ENUM_TIMEFRAMES)Period()))
     {
      g_log.Err("Not enough history to calibrate. Load more bars and restart.");
      return(INIT_FAILED);
     }

   g_log.Info(StringFormat("Timeframes | entry %s, intermediate %s, higher %s. Daily and weekly levels from D1/W1, accumulation range from M15 - all read internally, attach to ONE chart only.",
              EnumToString(g_ms.TfEntry()),EnumToString(g_ms.TfMid()),EnumToString(g_ms.TfHigh())));

   g_eng_e.SetLabel("entry");
   g_eng_m.SetLabel("mid");
   g_eng_h.SetLabel("high");

   SetPriors();
   //--- The learned weights belong to a symbol AND a timeframe: setups on
   //--- M5 and on H1 have different base rates, so a single file would let
   //--- one contaminate the other if the chart period is ever changed.
   string model_file=StringFormat("smc_agent_model_%s_%s.csv",_Symbol,
                                  EnumToString((ENUM_TIMEFRAMES)Period()));
   g_model.Init(F_COUNT,g_priors,GetPointer(g_log),model_file,InpWarmupSamples,-0.35);
   if(InpResetModel) { g_model.Reset(); g_log.Warn("Stored model discarded on request - restarting from the research priors"); }
   else if(!g_model.Load()) g_log.Info("No stored model found - starting from the research priors and observing");

   g_news.Init(_Symbol,GetPointer(g_log),g_gmt,InpNewsCsv);
   if(InpUseNews) g_news.Refresh(true);

   CNewsFilter *news_ptr=NULL;
   if(InpUseNews) news_ptr=GetPointer(g_news);
   g_conf.Init(GetPointer(g_ms),GetPointer(g_eng_e),GetPointer(g_eng_m),GetPointer(g_eng_h),
               news_ptr,GetPointer(g_model),GetPointer(g_log),
               g_gmt,InpNewsMinutesBefore,InpNewsMinutesAfter,InpNewsImportance);

   //--- per account and per symbol, so two challenges running side by side
   //--- can never inherit each other's capital, trading days or streaks
   string cap_source="";
   double capital=DetectInitialCapital(cap_source);
   long   login=AccountInfoInteger(ACCOUNT_LOGIN);
   string state_file=StringFormat("smc_agent_state_%s_%s.csv",IntegerToString(login),_Symbol);

   g_risk.Init(_Symbol,InpMagic,GetPointer(g_log),capital,InpPhase,PhaseTarget(),
               InpDailyLossPct,InpMaxLossPct,InpSoftDailyPct,InpHardDailyPct,InpSoftMaxPct,
               InpBaseRiskPct,InpDailyResetHour,InpMinTradingDays,state_file,cap_source);

   g_log.Info(StringFormat("Phase capital %.2f (%s). Balance now %.2f, equity %.2f.",
              g_risk.Initial(),cap_source,AccountInfoDouble(ACCOUNT_BALANCE),AccountInfoDouble(ACCOUNT_EQUITY)));
   if(AccountInfoDouble(ACCOUNT_EQUITY)<g_risk.OverallFloor())
      g_log.Err(StringFormat("Equity %.2f is already below the phase's overall floor %.2f - this account looks breached. Check the capital above before trading.",
                AccountInfoDouble(ACCOUNT_EQUITY),g_risk.OverallFloor()));

   g_exec.Init(_Symbol,InpMagic,InpSlippagePoints,GetPointer(g_log));
   g_journal.Init(F_COUNT);
   g_vbook.Init(F_COUNT,GetPointer(g_log),120);
   g_vis.Init(ChartID(),InpShowChart,InpShowPanel,InpPanelX,InpPanelY);

   g_sig.valid=false;
   g_sig.prob=0.0;

   g_log.Info(StringFormat("FTMO envelope: initial %.2f  daily floor %.2f  overall floor %.2f  target %.2f",
              g_risk.Initial(),g_risk.DailyFloor(),g_risk.OverallFloor(),g_risk.TargetEquity()));

   EventSetTimer(5);
   g_ready=true;
   SyncBrokerClock(true);
   AnalyzeAll();
   ReportSizingFeasibility();
   g_conf.Evaluate(g_sig);
   g_threshold=AcceptanceThreshold();
   Redraw();
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   g_model.Save();
   g_risk.SaveState();
   g_vis.Clear();
   g_log.Info(StringFormat("Shutting down (reason %d). Model saved with %d updates.",reason,(int)g_model.Updates()));
   g_log.Close();
  }

//+------------------------------------------------------------------+
//| Rebuild the whole SMC picture from the live candles              |
//+------------------------------------------------------------------+
bool AnalyzeAll()
  {
   if(!g_ms.Refresh()) return(false);
   MqlRates e[],m[],h[];
   g_ms.CopyEntry(e);
   g_ms.CopyMid(m);
   g_ms.CopyHigh(h);
   bool ok=g_eng_e.Analyze(e);
   ok=(g_eng_m.Analyze(m) && ok);
   ok=(g_eng_h.Analyze(h) && ok);
   return(ok);
  }

//+------------------------------------------------------------------+
void RedrawPanel()
  {
   g_vis.DrawPanel(GetPointer(g_ms),GetPointer(g_eng_e),GetPointer(g_conf),GetPointer(g_risk),
                   GetPointer(g_model),g_sig,ModeString(),g_threshold,g_last_action,
                   g_exec.OpenCount(),NewsLine(),g_gmt);
  }

//+------------------------------------------------------------------+
//| Full redraw: the chart layer only changes when the SMC map does, |
//| so it is rebuilt on bar closes, not on every timer tick.         |
//+------------------------------------------------------------------+
void Redraw()
  {
   g_vis.DrawChart(GetPointer(g_ms),GetPointer(g_eng_e),GetPointer(g_conf),g_gmt);
   //--- the entry / stop / target overlay belongs to a live plan only.
   //--- Once the agent is flat and holds no signal it must come off the
   //--- chart rather than linger as a picture of a finished trade.
   if(!g_sig.valid && g_exec.OpenCount()==0) g_vis.ClearSignal();
   RedrawPanel();
  }

//+------------------------------------------------------------------+
string ModeString()
  {
   if(g_risk.DayLocked()) return("LOCKED");
   if(!g_model.IsWarm())  return("WARM-UP");
   return("LIVE");
  }

//+------------------------------------------------------------------+
//| Learn from every real position that has been closed              |
//+------------------------------------------------------------------+
void HarvestClosedTrades()
  {
   for(int i=g_journal.Count()-1;i>=0;i--)
     {
      ulong t=g_journal.Ticket(i);
      if(PositionSelectByTicket(t)) continue;      // still open
      double profit=0.0;
      //--- The position is gone, but the closing deal may not be in the
      //--- terminal's history yet - OnTrade fires before it lands. A
      //--- missing deal is not a loss, so wait rather than teach the
      //--- model something false.
      if(!g_exec.ClosedResult(g_journal.PositionId(i),profit))
        {
         g_journal.MarkFail(i);
         if(g_journal.Fails(i)==1)
            g_log.Debug(StringFormat("Position #%s closed, waiting for the deal to reach history before learning from it",
                        IntegerToString((long)t)));
         if(g_journal.Fails(i)>600)
           {
            g_log.Warn(StringFormat("Gave up resolving #%s after 600 attempts - dropped WITHOUT training the model rather than labelling it blind",
                       IntegerToString((long)t)));
            g_journal.Remove(i);
           }
         continue;
        }
      double x[];
      g_journal.Vector(i,x);
      double y=(profit>0.0?1.0:0.0);
      g_model.Learn(x,y,1.0);
      g_model.Replay(1);
      g_model.Save();
      g_risk.OnTradeClosed(profit);
      g_log.Think(StringFormat("LEARN | real trade #%s closed at %.2f -> label %s | model acc %.0f%% after %d updates",
                  IntegerToString((long)t),profit,(y>0.5?"WIN":"LOSS"),g_model.Accuracy()*100.0,(int)g_model.Updates()));
      g_journal.Remove(i);
     }
  }

//+------------------------------------------------------------------+
//| In-trade management                                              |
//+------------------------------------------------------------------+
void ManagePositions()
  {
   int stop_bars=(InpTimeStopBars>0?InpTimeStopBars:(int)MathMax(15,g_eng_e.PivotLen()*8));
   double unit=g_eng_e.Unit();
   for(int i=g_journal.Count()-1;i>=0;i--)
     {
      ulong t=g_journal.Ticket(i);
      if(!PositionSelectByTicket(t)) continue;
      int    dir=g_journal.Dir(i);
      double entry=g_journal.Entry(i);
      double sl0=g_journal.Sl(i);
      double risk=MathAbs(entry-sl0);
      if(risk<=0.0) continue;
      double price=PositionGetDouble(POSITION_PRICE_CURRENT);
      double cur_sl=PositionGetDouble(POSITION_SL);
      double cur_tp=PositionGetDouble(POSITION_TP);
      double vol=PositionGetDouble(POSITION_VOLUME);
      double r=(dir==DIR_BULL?(price-entry):(entry-price))/risk;

      //--- 1 partial profit at the first objective
      if(!g_journal.PartialDone(i) && r>=InpPartialAtR && InpPartialPercent>0.0)
        {
         double part=vol*InpPartialPercent/100.0;
         if(g_exec.PartialClose(t,part))
           {
            g_journal.SetPartial(i);
            g_log.Think(StringFormat("MANAGE | +%.2fR reached, %.0f%% closed on #%s, remainder runs to the second pool",
                        r,InpPartialPercent,IntegerToString((long)t)));
           }
         else g_journal.SetPartial(i);
        }

      //--- 2 break even
      if(!g_journal.BeDone(i) && r>=InpBreakEvenAtR)
        {
         double spread=g_ms.SpreadPrice();
         double be=(dir==DIR_BULL?entry+spread:entry-spread);
         if((dir==DIR_BULL && be>cur_sl) || (dir==DIR_BEAR && (be<cur_sl || cur_sl<=0.0)))
            if(g_exec.ModifySl(t,be,cur_tp))
              {
               g_journal.SetBe(i);
               g_log.Think(StringFormat("MANAGE | risk removed on #%s, stop at break even",IntegerToString((long)t)));
              }
        }

      //--- 3 structural trail
      if(r>=InpTrailAfterR)
        {
         double trail=(dir==DIR_BULL?price-unit*1.2:price+unit*1.2);
         //--- prefer the last internal swing as the trailing anchor
         SSwing s;
         for(int k=g_eng_e.SwingCount()-1;k>=0;k--)
           {
            if(!g_eng_e.GetSwing(k,s)) break;
            if(dir==DIR_BULL && s.dir==DIR_BEAR && s.price<price) { trail=MathMax(trail,s.price-unit*0.3); break; }
            if(dir==DIR_BEAR && s.dir==DIR_BULL && s.price>price) { trail=MathMin(trail,s.price+unit*0.3); break; }
           }
         if((dir==DIR_BULL && trail>cur_sl) || (dir==DIR_BEAR && trail<cur_sl))
            g_exec.ModifySl(t,trail,cur_tp);
        }

      //--- 4 time stop: the raid never expanded
      int bars_open=Bars(_Symbol,(ENUM_TIMEFRAMES)Period(),g_journal.Opened(i),SmcNow());
      if(bars_open>=stop_bars && r<0.5)
        {
         g_log.Think(StringFormat("MANAGE | #%s spent %d bars without expansion (%.2fR) - releasing the risk",IntegerToString((long)t),bars_open,r));
         g_exec.Close(t);
        }
     }
  }

//+------------------------------------------------------------------+
//| Guard rails that run on every tick                               |
//+------------------------------------------------------------------+
void RiskGuards()
  {
   g_risk.NewDayCheck();
   string reason="";
   if(g_risk.MustFlatten(reason))
     {
      if(g_exec.OpenCount()>0) g_exec.CloseAll(reason);
      g_risk.Lock(reason);
      g_last_action="flattened: "+reason;
      return;
     }
   //--- FTMO funded accounts may not open or close inside the release
   //--- window, so the agent steps aside before it opens
   if(InpUseNews && InpFlattenBeforeNews && g_exec.OpenCount()>0)
     {
      SNewsEvent e;
      int mins=0;
      if(g_news.NextEvent(SmcNow(),InpNewsImportance,e,mins) && mins<=InpNewsMinutesBefore+2 && mins>=0)
        {
         g_exec.CloseAll(StringFormat("standing aside before %s (%s) in %d min",e.name,e.currency,mins));
         g_last_action=StringFormat("flat before %s",e.name);
        }
     }
  }

//+------------------------------------------------------------------+
//| One decision cycle, executed on the close of every bar           |
//+------------------------------------------------------------------+
bool OnBarClose()
  {
   if(!AnalyzeAll())
     {
      g_log.Warn("Chart data not ready on this close - will retry on the next tick");
      return(false);
     }
   if(InpUseNews) g_news.Refresh(false);

   //--- resolve the observation book against the bar that just closed
   if(InpVirtualLearning)
     {
      int done=g_vbook.Resolve(g_ms.EHigh(1),g_ms.ELow(1),GetPointer(g_model));
      if(done>0) g_model.Save();
     }

   HarvestClosedTrades();

   //--- read the chart -------------------------------------------------
   bool have=g_conf.Evaluate(g_sig);
   g_threshold=AcceptanceThreshold();

   double x[];
   g_conf.GetVector(x);

   //--- decision log ---------------------------------------------------
   g_log.Rule(StringFormat("BAR CLOSE %s  %s  %s  price %.2f",
              TimeToString(g_ms.ETime(1),TIME_DATE|TIME_MINUTES),_Symbol,
              EnumToString((ENUM_TIMEFRAMES)Period()),g_ms.EClose(1)));
   g_log.Think(StringFormat("READ   | %s %s | %s %s | entry swing %s internal %s | volatility %.2fx | %s",
               EnumToString(g_ms.TfHigh()),SmcDirStr(g_conf.BiasHtf()),
               EnumToString(g_ms.TfMid()),SmcDirStr(g_conf.BiasMid()),
               SmcDirStr(g_eng_e.Trend()),SmcDirStr(g_eng_e.InternalTrend()),
               g_ms.VolRegime(),
               (g_eng_e.SweepValid()?StringFormat("raid on %s %d bars ago",g_eng_e.SweepPool(),g_eng_e.SweepAge()):"no raid")));

   if(g_log.Level()>=LOG_DECIDE)
     {
      string fl="";
      for(int i=0;i<F_COUNT;i++)
        {
         SFactor f;
         if(!g_conf.GetFactor(i,f)) continue;
         if(MathAbs(f.contrib)<0.02) continue;
         fl+=StringFormat("%s %+0.2f; ",f.name,f.contrib);
        }
      if(fl!="") g_log.Think("FACTORS| "+fl);
     }

   if(!have)
     {
      g_last_action=StringFormat("no trade - %s",(g_conf.Veto()==""?"no qualified setup":g_conf.Veto()));
      g_log.Think("DECIDE | "+g_last_action);
      Redraw();
      return(true);
     }

   g_log.Think(StringFormat("PLAN   | %s",g_sig.rationale));
   g_log.Think(StringFormat("MODEL  | probability %.1f%% vs acceptance %.1f%% (%s, %d observations, accuracy %.0f%%)",
               g_sig.prob*100.0,g_threshold*100.0,(g_model.IsWarm()?"trained":"warm-up"),
               (int)g_model.Updates(),g_model.Accuracy()*100.0));

   //--- gates -----------------------------------------------------------
   string block="";
   bool   take=true;

   if(g_sig.prob<g_threshold) { take=false; block=StringFormat("probability %.0f%% below the %.0f%% the agent requires now",g_sig.prob*100.0,g_threshold*100.0); }

   string rreason="";
   if(take && !g_risk.CanOpen(rreason)) { take=false; block="risk envelope: "+rreason; }
   if(take && g_exec.OpenCount()>=InpMaxPositions) { take=false; block="maximum simultaneous exposure already open"; }
   if(take && g_last_signal==g_sig.bar_time) { take=false; block="already acted on this bar"; }

   double lots=0.0;
   double risk_dist=MathAbs(g_sig.entry-g_sig.sl);
   if(take)
     {
      double money=g_risk.RiskMoney(g_sig.prob);
      lots=g_risk.Lots(money,risk_dist);
      if(lots<=0.0)
        {
         take=false;
         block="compliant position size rounds below the minimum lot";
         g_size_skips++;
         if(g_size_skips==3 || (g_size_skips>3 && g_size_skips%20==0))
           {
            double want=0,minrisk=0,minpct=0,needpct=0;
            g_risk.SizingFeasible(risk_dist,want,minrisk,minpct,needpct);
            g_log.Err(StringFormat("Sizing | %d setups in a row skipped because the position cannot be sized. One minimum lot risks %.2f%% of capital against a %.2f%% budget on a %.2f stop. Raise InpBaseRiskPct to >= %.2f%% or use a larger account - the agent will not do it for you.",
                      g_size_skips,minpct,g_risk.BaseRiskPct(),risk_dist,needpct));
           }
        }
      else
        {
         string wc="";
         if(!g_risk.WorstCaseAcceptable(lots,risk_dist,wc)) { take=false; block=wc; }
         else g_log.Think(StringFormat("SIZE   | risking %.2f (%.2f%% of the phase capital) with %.2f lots, stop %.2f away",
                          money,money/g_risk.Initial()*100.0,lots,risk_dist));
        }
     }

   if(!take)
     {
      g_last_action="stood aside - "+block;
      g_log.Think("DECIDE | stand aside: "+block);
      //--- keep learning from what was skipped
      if(InpVirtualLearning) g_vbook.Add(x,g_sig.entry,g_sig.sl,g_sig.tp1,g_sig.dir);
      Redraw();
      return(true);
     }

   //--- execute ---------------------------------------------------------
   string comment=StringFormat("SMCAI %s p%.0f",(g_sig.dir==DIR_BULL?"L":"S"),g_sig.prob*100.0);
   if(g_exec.Open(g_sig.dir,lots,g_sig.sl,g_sig.tp2,comment))
     {
      ulong ticket=0,posid=0;
      for(int i=PositionsTotal()-1;i>=0;i--)
        {
         ulong t=PositionGetTicket(i);
         if(t==0) continue;
         if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
         if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
         if(g_journal.IndexOf(t)>=0) continue;
         ticket=t;
         //--- history is indexed by the position identifier, which is not
         //--- always the same number as the position ticket
         posid=(ulong)PositionGetInteger(POSITION_IDENTIFIER);
         break;
        }
      if(ticket>0)
        {
         g_size_skips=0;
         g_journal.Add(ticket,posid,x,g_sig.entry,g_sig.sl,g_sig.tp1,g_sig.dir);
         g_risk.OnTradeOpened();
         g_last_signal=g_sig.bar_time;
         g_last_action=StringFormat("%s %.2f lots @ %.2f",SmcDirShort(g_sig.dir),lots,g_sig.entry);
         g_log.Think(StringFormat("EXECUTE| #%s %s",IntegerToString((long)ticket),g_last_action));
         g_vis.DrawSignal(g_sig,g_ms.ETime(1));
        }
      else g_log.Warn("Position opened but could not be matched to a ticket - it will be managed by its stop and target only");
     }
   else
     {
      g_last_action="order rejected by the server";
      if(InpVirtualLearning) g_vbook.Add(x,g_sig.entry,g_sig.sl,g_sig.tp1,g_sig.dir);
     }

   Redraw();
   return(true);
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   if(!g_ready) return;
   RiskGuards();
   ManagePositions();

   datetime bt=(datetime)SeriesInfoInteger(_Symbol,(ENUM_TIMEFRAMES)Period(),SERIES_LASTBAR_DATE);
   if(bt==0 || bt==g_last_bar) return;
   g_last_bar=bt;
   //--- if the chart data was not ready this bar is retried on the next
   //--- tick instead of being silently skipped
   if(!OnBarClose()) g_last_bar=0;
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   if(!g_ready) return;
   g_risk.NewDayCheck();
   //--- cheap and idempotent: only acts when the broker offset actually moves
   SyncBrokerClock();
   RedrawPanel();
  }

//+------------------------------------------------------------------+
void OnTrade()
  {
   if(!g_ready) return;
   HarvestClosedTrades();
  }

//+------------------------------------------------------------------+
double OnTester()
  {
   //--- optimisation criterion that respects the FTMO shape of the task:
   //--- profit is only worth anything if the drawdown stayed compliant
   double profit=TesterStatistics(STAT_PROFIT);
   double dd    =TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   double trades=TesterStatistics(STAT_TRADES);
   if(trades<10) return(0.0);
   if(dd>=10.0)  return(-1.0);
   double pf=TesterStatistics(STAT_PROFIT_FACTOR);
   return(profit*(1.0-dd/10.0)*MathMin(pf,3.0));
  }
//+------------------------------------------------------------------+
