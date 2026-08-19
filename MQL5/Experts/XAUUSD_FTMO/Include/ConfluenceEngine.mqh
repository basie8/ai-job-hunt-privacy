//+------------------------------------------------------------------+
//|                                             ConfluenceEngine.mqh |
//|  Multi-timeframe, weighted-confluence signal engine for XAUUSD.  |
//|                                                                  |
//|  DESIGN NOTE - why a SCORE and not an AND-chain                  |
//|  ------------------------------------------------------------    |
//|  Eleven indicators wired as a boolean AND would fire perhaps      |
//|  twice a month; the brief asks for at least one trade a day.     |
//|  So each component contributes WEIGHTED POINTS to a bull score    |
//|  and a bear score. A trade needs a high total AND a clear         |
//|  dominance margin over the opposite side. That keeps the         |
//|  confluence requirement strict in aggregate while letting a       |
//|  single lagging indicator veto nothing on its own.               |
//|                                                                  |
//|  A small number of conditions remain HARD gates because they     |
//|  are about tradeability rather than direction: volatility        |
//|  regime, over-extension from the mean, and trend strength.       |
//|                                                                  |
//|  All evaluation happens on the LAST CLOSED BAR (shift 1) so the  |
//|  signal cannot repaint.                                          |
//+------------------------------------------------------------------+
#ifndef __XAUUSD_FTMO_CONFLUENCE_MQH__
#define __XAUUSD_FTMO_CONFLUENCE_MQH__

//--- version stamp. The EA checks for this, so copying a new .mq5
//--- next to a stale .mqh fails with one named error instead of forty.
#define XFC_V_CONFLUENCE_3

#include "CoreDefs.mqh"

#define CONF_COMPONENTS 11

//+------------------------------------------------------------------+
class CConfluenceEngine
  {
private:
   string            m_symbol;
   ENUM_TIMEFRAMES   m_tfTrade;
   ENUM_TIMEFRAMES   m_tfMid;
   ENUM_TIMEFRAMES   m_tfHigh;

   //--- indicator handles
   int               m_hEmaFastT, m_hEmaSlowT;       // trade TF 8 / 21
   int               m_hEmaFastM, m_hEmaSlowM;       // mid   TF 21 / 50
   int               m_hEmaFastH, m_hEmaSlowH;       // high  TF 50 / 200
   int               m_hRsi, m_hMacd, m_hAdx, m_hStoch, m_hBands, m_hAtr;

   //--- periods
   int               m_emaFastT, m_emaSlowT;
   int               m_emaFastM, m_emaSlowM;
   int               m_emaFastH, m_emaSlowH;
   int               m_rsiPeriod, m_adxPeriod, m_atrPeriod;
   int               m_stochK, m_stochD, m_stochSlow;
   int               m_bandsPeriod;
   double            m_bandsDev;
   int               m_macdFast, m_macdSlow, m_macdSignal;

   //--- thresholds
   double            m_adxMin;
   double            m_rsiBullLow, m_rsiBullHigh;
   double            m_rsiBearLow, m_rsiBearHigh;
   double            m_maxExtensionAtr;     // hard gate: distance from EMA slow (trade TF)
   double            m_minAtrPrice;         // hard gate: volatility floor (absolute mode)
   double            m_maxAtrPrice;         // hard gate: volatility ceiling (absolute mode)
   ENUM_ATR_BAND_MODE m_atrBandMode;
   double            m_atrMinRel;           // relative mode: ATR / its own average
   double            m_atrMaxRel;
   double            m_atrMinPct;           // percent mode: ATR as % of price
   double            m_atrMaxPct;
   int               m_atrAvgPeriod;        // bars in the long-run ATR average
   double            m_volumeFactor;

   //--- weights
   double            m_w[CONF_COMPONENTS];
   ConfluenceItem    m_items[CONF_COMPONENTS];

   //--- cached readings from the last Evaluate()
   double            m_lastAtr;
   double            m_lastAdx;
   double            m_lastRsi;
   double            m_vwap;
   string            m_gateReason;
   ENUM_GATE_REASON  m_gateCode;
   double            m_lastAtrRatio;

   //--- helpers
   bool              CopyOne(const int handle, const int buffer, const int shift, double &out);
   bool              CopyTwo(const int handle, const int buffer, const int shift, double &cur, double &prev);
   double            DailyVwap(void);
   double            PivotPoint(void);
   bool              SwingLow(const int lookback, const int shift, double &out);
   bool              SwingHigh(const int lookback, const int shift, double &out);
   void              Score(const int idx, const string name, const double bull, const double bear);

public:
                     CConfluenceEngine(void);
                    ~CConfluenceEngine(void);

   bool              Init(const string symbol,
                          const ENUM_TIMEFRAMES tfTrade,
                          const ENUM_TIMEFRAMES tfMid,
                          const ENUM_TIMEFRAMES tfHigh);

   void              SetPeriods(const int emaFastT, const int emaSlowT,
                                const int emaFastM, const int emaSlowM,
                                const int emaFastH, const int emaSlowH,
                                const int rsiPeriod, const int adxPeriod, const int atrPeriod,
                                const int stochK, const int stochD, const int stochSlow,
                                const int bandsPeriod, const double bandsDev,
                                const int macdFast, const int macdSlow, const int macdSignal);

   void              SetAtrBand(const ENUM_ATR_BAND_MODE mode,
                                 const double minRel, const double maxRel,
                                 const double minPct, const double maxPct,
                                 const int avgPeriod);
   double            AtrAverage(const int shift);
   void              SetThresholds(const double adxMin,
                                   const double rsiBullLow, const double rsiBullHigh,
                                   const double rsiBearLow, const double rsiBearHigh,
                                   const double maxExtensionAtr,
                                   const double minAtrPrice, const double maxAtrPrice,
                                   const double volumeFactor);

   void              SetWeights(const double wRegime, const double wMidTrend, const double wFastTrend,
                                const double wAdx, const double wRsi, const double wMacd,
                                const double wStoch, const double wVwap, const double wBands,
                                const double wStructure, const double wVolume);

   //--- returns SIGNAL_NONE when no side is dominant or a hard gate blocks
   ENUM_SIGNAL_DIR   Evaluate(const double scoreThreshold,
                              const double dominanceMargin,
                              SignalSnapshot &snap);

   //--- stop / target construction, ATR + structure aware
   bool              BuildLevels(const ENUM_SIGNAL_DIR dir,
                                 const double atr,
                                 const double slAtrMult,
                                 const int    swingLookback,
                                 const double swingBufferAtr,
                                 const double minStopAtr,
                                 const double maxStopAtr,
                                 const double rMultiple1,
                                 const double rMultiple2,
                                 SignalSnapshot &snap);

   double            Atr(void)        const { return m_lastAtr; }
   double            Adx(void)        const { return m_lastAdx; }
   double            Rsi(void)        const { return m_lastRsi; }
   double            Vwap(void)       const { return m_vwap; }
   string            BreakdownText(void) const;
   ENUM_GATE_REASON  GateCode(void)   const { return m_gateCode; }
   string            GateReason(void) const { return m_gateReason; }
   double            AtrRatio(void)   const { return m_lastAtrRatio; }
   double            AtrHandleValue(const int shift);
  };

//+------------------------------------------------------------------+
CConfluenceEngine::CConfluenceEngine(void)
  {
   m_symbol   = "";
   m_tfTrade  = PERIOD_M15;
   m_tfMid    = PERIOD_H1;
   m_tfHigh   = PERIOD_H4;

   m_hEmaFastT = m_hEmaSlowT = INVALID_HANDLE;
   m_hEmaFastM = m_hEmaSlowM = INVALID_HANDLE;
   m_hEmaFastH = m_hEmaSlowH = INVALID_HANDLE;
   m_hRsi = m_hMacd = m_hAdx = m_hStoch = m_hBands = m_hAtr = INVALID_HANDLE;

   m_emaFastT = 8;   m_emaSlowT = 21;
   m_emaFastM = 21;  m_emaSlowM = 50;
   m_emaFastH = 50;  m_emaSlowH = 200;
   m_rsiPeriod = 14; m_adxPeriod = 14; m_atrPeriod = 14;
   m_stochK = 14;    m_stochD = 3;     m_stochSlow = 3;
   m_bandsPeriod = 20; m_bandsDev = 2.0;
   m_macdFast = 12;  m_macdSlow = 26;  m_macdSignal = 9;

   m_adxMin          = 20.0;
   m_rsiBullLow      = 45.0;  m_rsiBullHigh = 78.0;
   m_rsiBearLow      = 22.0;  m_rsiBearHigh = 55.0;
   m_maxExtensionAtr = 2.2;
   m_minAtrPrice     = 0.0;
   m_maxAtrPrice     = 0.0;
   m_atrBandMode     = ATR_BAND_RELATIVE;
   m_atrMinRel       = 0.60;
   m_atrMaxRel       = 2.50;
   m_atrMinPct       = 0.020;
   m_atrMaxPct       = 0.350;
   m_atrAvgPeriod    = 100;
   m_gateCode        = GATE_OK;
   m_lastAtrRatio    = 0.0;
   m_volumeFactor    = 1.10;

   m_lastAtr = m_lastAdx = m_lastRsi = 0.0;
   m_vwap = 0.0;
   m_gateReason = "";

   double defaults[CONF_COMPONENTS] = {12, 12, 10, 12, 8, 10, 8, 8, 6, 8, 6};
   for(int i = 0; i < CONF_COMPONENTS; i++)
      m_w[i] = defaults[i];
  }

//+------------------------------------------------------------------+
CConfluenceEngine::~CConfluenceEngine(void)
  {
   if(m_hEmaFastT != INVALID_HANDLE) IndicatorRelease(m_hEmaFastT);
   if(m_hEmaSlowT != INVALID_HANDLE) IndicatorRelease(m_hEmaSlowT);
   if(m_hEmaFastM != INVALID_HANDLE) IndicatorRelease(m_hEmaFastM);
   if(m_hEmaSlowM != INVALID_HANDLE) IndicatorRelease(m_hEmaSlowM);
   if(m_hEmaFastH != INVALID_HANDLE) IndicatorRelease(m_hEmaFastH);
   if(m_hEmaSlowH != INVALID_HANDLE) IndicatorRelease(m_hEmaSlowH);
   if(m_hRsi      != INVALID_HANDLE) IndicatorRelease(m_hRsi);
   if(m_hMacd     != INVALID_HANDLE) IndicatorRelease(m_hMacd);
   if(m_hAdx      != INVALID_HANDLE) IndicatorRelease(m_hAdx);
   if(m_hStoch    != INVALID_HANDLE) IndicatorRelease(m_hStoch);
   if(m_hBands    != INVALID_HANDLE) IndicatorRelease(m_hBands);
   if(m_hAtr      != INVALID_HANDLE) IndicatorRelease(m_hAtr);
  }

//+------------------------------------------------------------------+
void CConfluenceEngine::SetPeriods(const int emaFastT, const int emaSlowT,
                                   const int emaFastM, const int emaSlowM,
                                   const int emaFastH, const int emaSlowH,
                                   const int rsiPeriod, const int adxPeriod, const int atrPeriod,
                                   const int stochK, const int stochD, const int stochSlow,
                                   const int bandsPeriod, const double bandsDev,
                                   const int macdFast, const int macdSlow, const int macdSignal)
  {
   m_emaFastT = emaFastT; m_emaSlowT = emaSlowT;
   m_emaFastM = emaFastM; m_emaSlowM = emaSlowM;
   m_emaFastH = emaFastH; m_emaSlowH = emaSlowH;
   m_rsiPeriod = rsiPeriod; m_adxPeriod = adxPeriod; m_atrPeriod = atrPeriod;
   m_stochK = stochK; m_stochD = stochD; m_stochSlow = stochSlow;
   m_bandsPeriod = bandsPeriod; m_bandsDev = bandsDev;
   m_macdFast = macdFast; m_macdSlow = macdSlow; m_macdSignal = macdSignal;
  }

//+------------------------------------------------------------------+
void CConfluenceEngine::SetAtrBand(const ENUM_ATR_BAND_MODE mode,
                                   const double minRel, const double maxRel,
                                   const double minPct, const double maxPct,
                                   const int avgPeriod)
  {
   m_atrBandMode  = mode;
   m_atrMinRel    = minRel;
   m_atrMaxRel    = maxRel;
   m_atrMinPct    = minPct;
   m_atrMaxPct    = maxPct;
   m_atrAvgPeriod = MathMax(20, avgPeriod);
  }

//+------------------------------------------------------------------+
//| Mean ATR over the long-run window, used as the reference for the |
//| self-adjusting volatility band.                                  |
//+------------------------------------------------------------------+
double CConfluenceEngine::AtrAverage(const int shift)
  {
   double buf[];
   ArraySetAsSeries(buf, true);
   int got = CopyBuffer(m_hAtr, 0, shift, m_atrAvgPeriod, buf);
   if(got < 20)
      return 0.0;

   double sum = 0.0;
   int n = 0;
   for(int i = 0; i < got; i++)
     {
      if(buf[i] > 0.0 && buf[i] != EMPTY_VALUE)
        {
         sum += buf[i];
         n++;
        }
     }
   return (n > 0 ? sum / n : 0.0);
  }

//+------------------------------------------------------------------+
void CConfluenceEngine::SetThresholds(const double adxMin,
                                      const double rsiBullLow, const double rsiBullHigh,
                                      const double rsiBearLow, const double rsiBearHigh,
                                      const double maxExtensionAtr,
                                      const double minAtrPrice, const double maxAtrPrice,
                                      const double volumeFactor)
  {
   m_adxMin          = adxMin;
   m_rsiBullLow      = rsiBullLow;
   m_rsiBullHigh     = rsiBullHigh;
   m_rsiBearLow      = rsiBearLow;
   m_rsiBearHigh     = rsiBearHigh;
   m_maxExtensionAtr = maxExtensionAtr;
   m_minAtrPrice     = minAtrPrice;
   m_maxAtrPrice     = maxAtrPrice;
   m_volumeFactor    = volumeFactor;
  }

//+------------------------------------------------------------------+
void CConfluenceEngine::SetWeights(const double wRegime, const double wMidTrend, const double wFastTrend,
                                   const double wAdx, const double wRsi, const double wMacd,
                                   const double wStoch, const double wVwap, const double wBands,
                                   const double wStructure, const double wVolume)
  {
   m_w[0]  = wRegime;
   m_w[1]  = wMidTrend;
   m_w[2]  = wFastTrend;
   m_w[3]  = wAdx;
   m_w[4]  = wRsi;
   m_w[5]  = wMacd;
   m_w[6]  = wStoch;
   m_w[7]  = wVwap;
   m_w[8]  = wBands;
   m_w[9]  = wStructure;
   m_w[10] = wVolume;
  }

//+------------------------------------------------------------------+
bool CConfluenceEngine::Init(const string symbol,
                             const ENUM_TIMEFRAMES tfTrade,
                             const ENUM_TIMEFRAMES tfMid,
                             const ENUM_TIMEFRAMES tfHigh)
  {
   m_symbol  = symbol;
   m_tfTrade = tfTrade;
   m_tfMid   = tfMid;
   m_tfHigh  = tfHigh;

   m_hEmaFastT = iMA(m_symbol, m_tfTrade, m_emaFastT, 0, MODE_EMA, PRICE_CLOSE);
   m_hEmaSlowT = iMA(m_symbol, m_tfTrade, m_emaSlowT, 0, MODE_EMA, PRICE_CLOSE);
   m_hEmaFastM = iMA(m_symbol, m_tfMid,   m_emaFastM, 0, MODE_EMA, PRICE_CLOSE);
   m_hEmaSlowM = iMA(m_symbol, m_tfMid,   m_emaSlowM, 0, MODE_EMA, PRICE_CLOSE);
   m_hEmaFastH = iMA(m_symbol, m_tfHigh,  m_emaFastH, 0, MODE_EMA, PRICE_CLOSE);
   m_hEmaSlowH = iMA(m_symbol, m_tfHigh,  m_emaSlowH, 0, MODE_EMA, PRICE_CLOSE);

   m_hRsi      = iRSI(m_symbol, m_tfTrade, m_rsiPeriod, PRICE_CLOSE);
   m_hMacd     = iMACD(m_symbol, m_tfTrade, m_macdFast, m_macdSlow, m_macdSignal, PRICE_CLOSE);
   m_hAdx      = iADX(m_symbol, m_tfTrade, m_adxPeriod);
   m_hStoch    = iStochastic(m_symbol, m_tfTrade, m_stochK, m_stochD, m_stochSlow, MODE_SMA, STO_LOWHIGH);
   m_hBands    = iBands(m_symbol, m_tfTrade, m_bandsPeriod, 0, m_bandsDev, PRICE_CLOSE);
   m_hAtr      = iATR(m_symbol, m_tfTrade, m_atrPeriod);

   if(m_hEmaFastT == INVALID_HANDLE || m_hEmaSlowT == INVALID_HANDLE ||
      m_hEmaFastM == INVALID_HANDLE || m_hEmaSlowM == INVALID_HANDLE ||
      m_hEmaFastH == INVALID_HANDLE || m_hEmaSlowH == INVALID_HANDLE ||
      m_hRsi == INVALID_HANDLE || m_hMacd == INVALID_HANDLE || m_hAdx == INVALID_HANDLE ||
      m_hStoch == INVALID_HANDLE || m_hBands == INVALID_HANDLE || m_hAtr == INVALID_HANDLE)
     {
      Print("[Confluence] FATAL: one or more indicator handles failed to initialise.");
      return false;
     }

   return true;
  }

//+------------------------------------------------------------------+
bool CConfluenceEngine::CopyOne(const int handle, const int buffer, const int shift, double &out)
  {
   double tmp[];
   ArraySetAsSeries(tmp, true);
   if(CopyBuffer(handle, buffer, shift, 1, tmp) < 1)
      return false;
   out = tmp[0];
   return (out != EMPTY_VALUE);
  }

//+------------------------------------------------------------------+
bool CConfluenceEngine::CopyTwo(const int handle, const int buffer, const int shift, double &cur, double &prev)
  {
   double tmp[];
   ArraySetAsSeries(tmp, true);
   if(CopyBuffer(handle, buffer, shift, 2, tmp) < 2)
      return false;
   cur  = tmp[0];
   prev = tmp[1];
   return (cur != EMPTY_VALUE && prev != EMPTY_VALUE);
  }

//+------------------------------------------------------------------+
double CConfluenceEngine::AtrHandleValue(const int shift)
  {
   double v = 0.0;
   if(CopyOne(m_hAtr, 0, shift, v))
      return v;
   return 0.0;
  }

//+------------------------------------------------------------------+
//| Session VWAP, anchored at the broker's midnight, built from M5.  |
//| Gold respects VWAP well intraday because so much of the volume   |
//| is algorithmic and benchmarked to it.                            |
//+------------------------------------------------------------------+
double CConfluenceEngine::DailyVwap(void)
  {
   datetime dayStart = DayStart(TimeTradeServer());

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(m_symbol, PERIOD_M5, dayStart, TimeTradeServer(), rates);
   if(copied <= 0)
      return 0.0;

   double pv = 0.0;
   double vv = 0.0;
   for(int i = 0; i < copied; i++)
     {
      double typical = (rates[i].high + rates[i].low + rates[i].close) / 3.0;
      double vol = (double)rates[i].tick_volume;
      if(vol <= 0.0)
         vol = 1.0;
      pv += typical * vol;
      vv += vol;
     }

   if(vv <= 0.0)
      return 0.0;
   return pv / vv;
  }

//+------------------------------------------------------------------+
//| Classic floor-trader pivot off yesterday's daily bar.            |
//+------------------------------------------------------------------+
double CConfluenceEngine::PivotPoint(void)
  {
   double h = iHigh(m_symbol, PERIOD_D1, 1);
   double l = iLow(m_symbol, PERIOD_D1, 1);
   double c = iClose(m_symbol, PERIOD_D1, 1);
   if(h <= 0.0 || l <= 0.0 || c <= 0.0)
      return 0.0;
   return (h + l + c) / 3.0;
  }

//+------------------------------------------------------------------+
bool CConfluenceEngine::SwingLow(const int lookback, const int shift, double &out)
  {
   double lows[];
   ArraySetAsSeries(lows, true);
   if(CopyLow(m_symbol, m_tfTrade, shift, lookback, lows) < lookback)
      return false;
   int idx = ArrayMinimum(lows, 0, lookback);
   if(idx < 0)
      return false;
   out = lows[idx];
   return true;
  }

//+------------------------------------------------------------------+
bool CConfluenceEngine::SwingHigh(const int lookback, const int shift, double &out)
  {
   double highs[];
   ArraySetAsSeries(highs, true);
   if(CopyHigh(m_symbol, m_tfTrade, shift, lookback, highs) < lookback)
      return false;
   int idx = ArrayMaximum(highs, 0, lookback);
   if(idx < 0)
      return false;
   out = highs[idx];
   return true;
  }

//+------------------------------------------------------------------+
void CConfluenceEngine::Score(const int idx, const string name, const double bull, const double bear)
  {
   m_items[idx].name   = name;
   m_items[idx].weight = m_w[idx];
   m_items[idx].bull   = bull;
   m_items[idx].bear   = bear;
  }

//+------------------------------------------------------------------+
//| MAIN EVALUATION                                                  |
//+------------------------------------------------------------------+
ENUM_SIGNAL_DIR CConfluenceEngine::Evaluate(const double scoreThreshold,
                                            const double dominanceMargin,
                                            SignalSnapshot &snap)
  {
   snap.dir          = SIGNAL_NONE;
   snap.bullScore    = 0.0;
   snap.bearScore    = 0.0;
   snap.atr          = 0.0;
   snap.entry        = 0.0;
   snap.stop         = 0.0;
   snap.tp1          = 0.0;
   snap.tp2          = 0.0;
   snap.riskDistance = 0.0;
   snap.reason       = "";
   m_gateReason      = "";
   m_gateCode        = GATE_OK;

   const int S = 1;   // last CLOSED bar - no repainting

   //================================================================
   // 1. raw readings
   //================================================================
   double atr = 0.0;
   if(!CopyOne(m_hAtr, 0, S, atr) || atr <= 0.0)
     {
      m_gateCode   = GATE_NO_DATA;
      m_gateReason = "ATR unavailable";
      snap.reason = m_gateReason;
      return SIGNAL_NONE;
     }
   m_lastAtr = atr;
   snap.atr  = atr;

   double emaFastT, emaFastTPrev, emaSlowT, emaSlowTPrev;
   double emaFastM, emaFastMPrev, emaSlowM, emaSlowMPrev;
   double emaFastH, emaSlowH;
   double rsi, rsiPrev;
   double macdMain, macdMainPrev, macdSig, macdSigPrev;
   double adx, diPlus, diMinus;
   double stochK, stochKPrev, stochD, stochDPrev;
   double bbUp, bbLo, bbMid;

   if(!CopyTwo(m_hEmaFastT, 0, S, emaFastT, emaFastTPrev)) { m_gateCode = GATE_NO_DATA; m_gateReason = "EMA fast (trade TF) unavailable"; snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyTwo(m_hEmaSlowT, 0, S, emaSlowT, emaSlowTPrev)) { m_gateCode = GATE_NO_DATA; m_gateReason = "EMA slow (trade TF) unavailable"; snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyTwo(m_hEmaFastM, 0, S, emaFastM, emaFastMPrev)) { m_gateCode = GATE_NO_DATA; m_gateReason = "EMA fast (mid TF) unavailable";   snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyTwo(m_hEmaSlowM, 0, S, emaSlowM, emaSlowMPrev)) { m_gateCode = GATE_NO_DATA; m_gateReason = "EMA slow (mid TF) unavailable";   snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyOne(m_hEmaFastH, 0, S, emaFastH))               { m_gateCode = GATE_NO_DATA; m_gateReason = "EMA fast (high TF) unavailable";  snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyOne(m_hEmaSlowH, 0, S, emaSlowH))               { m_gateCode = GATE_NO_DATA; m_gateReason = "EMA slow (high TF) unavailable";  snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyTwo(m_hRsi, 0, S, rsi, rsiPrev))                { m_gateCode = GATE_NO_DATA; m_gateReason = "RSI unavailable";   snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyTwo(m_hMacd, 0, S, macdMain, macdMainPrev))     { m_gateCode = GATE_NO_DATA; m_gateReason = "MACD unavailable";  snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyTwo(m_hMacd, 1, S, macdSig, macdSigPrev))       { m_gateCode = GATE_NO_DATA; m_gateReason = "MACD signal unavailable"; snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyOne(m_hAdx, 0, S, adx))                         { m_gateCode = GATE_NO_DATA; m_gateReason = "ADX unavailable";   snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyOne(m_hAdx, 1, S, diPlus))                      { m_gateCode = GATE_NO_DATA; m_gateReason = "DI+ unavailable";   snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyOne(m_hAdx, 2, S, diMinus))                     { m_gateCode = GATE_NO_DATA; m_gateReason = "DI- unavailable";   snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyTwo(m_hStoch, 0, S, stochK, stochKPrev))        { m_gateCode = GATE_NO_DATA; m_gateReason = "Stoch K unavailable"; snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyTwo(m_hStoch, 1, S, stochD, stochDPrev))        { m_gateCode = GATE_NO_DATA; m_gateReason = "Stoch D unavailable"; snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyOne(m_hBands, 0, S, bbMid))                     { m_gateCode = GATE_NO_DATA; m_gateReason = "BB mid unavailable";  snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyOne(m_hBands, 1, S, bbUp))                      { m_gateCode = GATE_NO_DATA; m_gateReason = "BB upper unavailable"; snap.reason = m_gateReason; return SIGNAL_NONE; }
   if(!CopyOne(m_hBands, 2, S, bbLo))                      { m_gateCode = GATE_NO_DATA; m_gateReason = "BB lower unavailable"; snap.reason = m_gateReason; return SIGNAL_NONE; }

   m_lastAdx = adx;
   m_lastRsi = rsi;

   double close  = iClose(m_symbol, m_tfTrade, S);
   double open   = iOpen(m_symbol, m_tfTrade, S);
   double prevHi = iHigh(m_symbol, m_tfTrade, S + 1);
   double prevLo = iLow(m_symbol, m_tfTrade, S + 1);

   if(close <= 0.0 || open <= 0.0)
     {
      m_gateCode   = GATE_NO_DATA;
      m_gateReason = "price data unavailable";
      snap.reason = m_gateReason;
      return SIGNAL_NONE;
     }

   //================================================================
   // 2. HARD GATES - tradeability, not direction
   //================================================================
   double lo = 0.0, hi = 0.0, measure = 0.0;
   string units = "";

   if(m_atrBandMode == ATR_BAND_RELATIVE)
     {
      double avg = AtrAverage(S);
      if(avg > 0.0)
        {
         measure = atr / avg;
         lo = m_atrMinRel;
         hi = m_atrMaxRel;
         units = "x avg";
        }
      m_lastAtrRatio = measure;
     }
   else
      if(m_atrBandMode == ATR_BAND_PERCENT)
        {
         if(close > 0.0)
           {
            measure = atr / close * 100.0;
            lo = m_atrMinPct;
            hi = m_atrMaxPct;
            units = "% of price";
           }
         m_lastAtrRatio = measure;
        }
      else
        {
         measure = atr;
         lo = m_minAtrPrice;
         hi = m_maxAtrPrice;
         units = "price";
         m_lastAtrRatio = atr;
        }

   if(measure > 0.0 && lo > 0.0 && measure < lo)
     {
      m_gateCode   = GATE_ATR_LOW;
      m_gateReason = StringFormat("ATR %.3f %s below floor %.3f - market too quiet",
                                  measure, units, lo);
      snap.reason = m_gateReason;
      return SIGNAL_NONE;
     }
   if(measure > 0.0 && hi > 0.0 && measure > hi)
     {
      m_gateCode   = GATE_ATR_HIGH;
      m_gateReason = StringFormat("ATR %.3f %s above ceiling %.3f - conditions too wild",
                                  measure, units, hi);
      snap.reason = m_gateReason;
      return SIGNAL_NONE;
     }
   if(adx < m_adxMin)
     {
      m_gateCode   = GATE_ADX_WEAK;
      m_gateReason = StringFormat("ADX %.1f below %.1f - no trend to ride", adx, m_adxMin);
      snap.reason = m_gateReason;
      return SIGNAL_NONE;
     }

   double extension = MathAbs(close - emaSlowT) / atr;
   if(m_maxExtensionAtr > 0.0 && extension > m_maxExtensionAtr)
     {
      m_gateCode   = GATE_OVEREXTENDED;
      m_gateReason = StringFormat("price %.1f ATR from EMA%d - too extended to chase", extension, m_emaSlowT);
      snap.reason = m_gateReason;
      return SIGNAL_NONE;
     }

   //================================================================
   // 3. WEIGHTED COMPONENTS
   //================================================================

   // -- 1. H4 macro regime -----------------------------------------
   double b = 0.0, s = 0.0;
   if(emaFastH > emaSlowH)
     {
      b = m_w[0] * 0.6;
      if(close > emaFastH)
         b = m_w[0];
     }
   if(emaFastH < emaSlowH)
     {
      s = m_w[0] * 0.6;
      if(close < emaFastH)
         s = m_w[0];
     }
   Score(0, "H4 regime", b, s);

   // -- 2. H1 intermediate trend + slope ----------------------------
   b = 0.0; s = 0.0;
   bool midUp   = (emaFastM > emaSlowM);
   bool midDn   = (emaFastM < emaSlowM);
   bool slopeUp = (emaFastM > emaFastMPrev);
   bool slopeDn = (emaFastM < emaFastMPrev);
   if(midUp)
      b = (slopeUp ? m_w[1] : m_w[1] * 0.55);
   if(midDn)
      s = (slopeDn ? m_w[1] : m_w[1] * 0.55);
   Score(1, "H1 trend", b, s);

   // -- 3. trade-TF trend + entry trigger candle --------------------
   b = 0.0; s = 0.0;
   bool fastUp = (emaFastT > emaSlowT && close > emaSlowT);
   bool fastDn = (emaFastT < emaSlowT && close < emaSlowT);
   if(fastUp)
     {
      b = m_w[2] * 0.6;
      if(close > open && close > prevHi)      // momentum close through the prior bar
         b = m_w[2];
      else
         if(close > open)
            b = m_w[2] * 0.8;
     }
   if(fastDn)
     {
      s = m_w[2] * 0.6;
      if(close < open && close < prevLo)
         s = m_w[2];
      else
         if(close < open)
            s = m_w[2] * 0.8;
     }
   Score(2, "TradeTF trend + trigger", b, s);

   // -- 4. ADX strength and directional index -----------------------
   b = 0.0; s = 0.0;
   double adxStrengthPts = m_w[3] * 0.5;
   if(adx >= m_adxMin + 8.0)
      adxStrengthPts = m_w[3] * 0.65;
   if(diPlus > diMinus)
      b = adxStrengthPts + m_w[3] * 0.35;
   else
      if(diMinus > diPlus)
         s = adxStrengthPts + m_w[3] * 0.35;
   Score(3, "ADX / DI", b, s);

   // -- 5. RSI momentum zone ----------------------------------------
   b = 0.0; s = 0.0;
   if(rsi >= m_rsiBullLow && rsi <= m_rsiBullHigh)
      b = (rsi > rsiPrev ? m_w[4] : m_w[4] * 0.6);
   if(rsi >= m_rsiBearLow && rsi <= m_rsiBearHigh)
      s = (rsi < rsiPrev ? m_w[4] : m_w[4] * 0.6);
   Score(4, "RSI zone", b, s);

   // -- 6. MACD -------------------------------------------------------
   b = 0.0; s = 0.0;
   double hist     = macdMain - macdSig;
   double histPrev = macdMainPrev - macdSigPrev;
   if(hist > 0.0)
      b = (hist > histPrev ? m_w[5] : m_w[5] * 0.6);
   if(hist < 0.0)
      s = (hist < histPrev ? m_w[5] : m_w[5] * 0.6);
   Score(5, "MACD", b, s);

   // -- 7. Stochastic pullback trigger --------------------------------
   b = 0.0; s = 0.0;
   bool kCrossUp   = (stochKPrev <= stochDPrev && stochK > stochD);
   bool kCrossDown = (stochKPrev >= stochDPrev && stochK < stochD);
   if(kCrossUp && stochKPrev < 45.0)
      b = m_w[6];                                  // textbook pullback finished
   else
      if(stochK > stochD)
         b = m_w[6] * 0.5;
   if(kCrossDown && stochKPrev > 55.0)
      s = m_w[6];
   else
      if(stochK < stochD)
         s = m_w[6] * 0.5;
   Score(6, "Stochastic", b, s);

   // -- 8. Session VWAP -----------------------------------------------
   b = 0.0; s = 0.0;
   m_vwap = DailyVwap();
   if(m_vwap > 0.0)
     {
      if(close > m_vwap)
         b = m_w[7];
      else
         if(close < m_vwap)
            s = m_w[7];
     }
   else
     {
      // no VWAP available - award neither side rather than skewing the score
      b = 0.0;
      s = 0.0;
     }
   Score(7, "Daily VWAP", b, s);

   // -- 9. Bollinger location (penalises buying the upper band) --------
   b = 0.0; s = 0.0;
   if(close > bbMid && close < bbUp)
      b = m_w[8];
   else
      if(close >= bbUp)
         b = m_w[8] * 0.2;                          // stretched, mean reversion risk
   if(close < bbMid && close > bbLo)
      s = m_w[8];
   else
      if(close <= bbLo)
         s = m_w[8] * 0.2;
   Score(8, "Bollinger location", b, s);

   // -- 10. Structure: pivot + previous day range ----------------------
   b = 0.0; s = 0.0;
   double pivot = PivotPoint();
   double pdh   = iHigh(m_symbol, PERIOD_D1, 1);
   double pdl   = iLow(m_symbol, PERIOD_D1, 1);
   if(pivot > 0.0)
     {
      if(close > pivot)
         b += m_w[9] * 0.5;
      else
         s += m_w[9] * 0.5;
     }
   if(pdh > 0.0 && pdl > 0.0)
     {
      double mid = (pdh + pdl) / 2.0;
      if(close > mid)
         b += m_w[9] * 0.5;
      else
         s += m_w[9] * 0.5;
     }
   Score(9, "Structure (pivot/PDH-PDL)", b, s);

   // -- 11. Volume confirmation -----------------------------------------
   b = 0.0; s = 0.0;
   long vols[];
   ArraySetAsSeries(vols, true);
   if(CopyTickVolume(m_symbol, m_tfTrade, S, 21, vols) == 21)
     {
      double avg = 0.0;
      for(int i = 1; i < 21; i++)
         avg += (double)vols[i];
      avg /= 20.0;
      double cur = (double)vols[0];
      if(avg > 0.0 && cur >= avg * m_volumeFactor)
        {
         if(close > open)
            b = m_w[10];
         else
            if(close < open)
               s = m_w[10];
        }
      else
         if(avg > 0.0 && cur >= avg * 0.8)
           {
            if(close > open)
               b = m_w[10] * 0.4;
            else
               if(close < open)
                  s = m_w[10] * 0.4;
           }
     }
   Score(10, "Volume", b, s);

   //================================================================
   // 4. totals, normalised to 0..100
   //================================================================
   double totalWeight = 0.0;
   double bullRaw = 0.0;
   double bearRaw = 0.0;
   for(int i = 0; i < CONF_COMPONENTS; i++)
     {
      totalWeight += m_w[i];
      bullRaw     += m_items[i].bull;
      bearRaw     += m_items[i].bear;
     }
   if(totalWeight <= 0.0)
      totalWeight = 1.0;

   snap.bullScore = bullRaw / totalWeight * 100.0;
   snap.bearScore = bearRaw / totalWeight * 100.0;

   //================================================================
   // 5. verdict
   //================================================================
   double diff = snap.bullScore - snap.bearScore;

   if(snap.bullScore >= scoreThreshold && diff >= dominanceMargin)
     {
      snap.dir = SIGNAL_BUY;
      snap.reason = StringFormat("BUY  bull=%.1f bear=%.1f margin=%.1f", snap.bullScore, snap.bearScore, diff);
      return SIGNAL_BUY;
     }

   if(snap.bearScore >= scoreThreshold && (-diff) >= dominanceMargin)
     {
      snap.dir = SIGNAL_SELL;
      snap.reason = StringFormat("SELL bull=%.1f bear=%.1f margin=%.1f", snap.bullScore, snap.bearScore, -diff);
      return SIGNAL_SELL;
     }

   m_gateCode  = GATE_NO_EDGE;
   snap.reason = StringFormat("no edge (bull=%.1f bear=%.1f, need %.1f + %.1f margin)",
                              snap.bullScore, snap.bearScore, scoreThreshold, dominanceMargin);
   return SIGNAL_NONE;
  }

//+------------------------------------------------------------------+
//| Builds stop and targets.                                         |
//| The stop is the WIDER of an ATR stop and the last swing, so it   |
//| sits behind structure rather than inside the noise. It is then   |
//| clamped so a volatility spike cannot produce an absurd risk      |
//| distance (and therefore an absurdly small lot).                  |
//+------------------------------------------------------------------+
bool CConfluenceEngine::BuildLevels(const ENUM_SIGNAL_DIR dir,
                                    const double atr,
                                    const double slAtrMult,
                                    const int    swingLookback,
                                    const double swingBufferAtr,
                                    const double minStopAtr,
                                    const double maxStopAtr,
                                    const double rMultiple1,
                                    const double rMultiple2,
                                    SignalSnapshot &snap)
  {
   if(dir == SIGNAL_NONE || atr <= 0.0)
      return false;

   double ask = SymbolInfoDouble(m_symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(m_symbol, SYMBOL_BID);
   if(ask <= 0.0 || bid <= 0.0)
      return false;

   double entry = (dir == SIGNAL_BUY ? ask : bid);
   double atrStop = atr * slAtrMult;
   double stop = 0.0;

   if(dir == SIGNAL_BUY)
     {
      double swing = 0.0;
      double structStop = entry - atrStop;
      if(SwingLow(swingLookback, 1, swing) && swing > 0.0)
         structStop = MathMin(structStop, swing - atr * swingBufferAtr);
      stop = structStop;
     }
   else
     {
      double swing = 0.0;
      double structStop = entry + atrStop;
      if(SwingHigh(swingLookback, 1, swing) && swing > 0.0)
         structStop = MathMax(structStop, swing + atr * swingBufferAtr);
      stop = structStop;
     }

   double risk = MathAbs(entry - stop);

   // clamp the risk distance into a sane ATR band
   double minRisk = atr * minStopAtr;
   double maxRisk = atr * maxStopAtr;
   if(minRisk > 0.0 && risk < minRisk)
      risk = minRisk;
   if(maxRisk > 0.0 && risk > maxRisk)
      risk = maxRisk;

   // respect the broker's stop level
   long   stopLevelPts = SymbolInfoInteger(m_symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double point        = SymbolInfoDouble(m_symbol, SYMBOL_POINT);
   double minBroker    = (double)stopLevelPts * point * 1.5;
   if(minBroker > 0.0 && risk < minBroker)
      risk = minBroker;

   if(dir == SIGNAL_BUY)
     {
      stop     = entry - risk;
      snap.tp1 = entry + risk * rMultiple1;
      snap.tp2 = entry + risk * rMultiple2;
     }
   else
     {
      stop     = entry + risk;
      snap.tp1 = entry - risk * rMultiple1;
      snap.tp2 = entry - risk * rMultiple2;
     }

   snap.entry        = NormalizePriceToTick(m_symbol, entry);
   snap.stop         = NormalizePriceToTick(m_symbol, stop);
   snap.tp1          = NormalizePriceToTick(m_symbol, snap.tp1);
   snap.tp2          = NormalizePriceToTick(m_symbol, snap.tp2);
   snap.riskDistance = risk;

   return (risk > 0.0);
  }

//+------------------------------------------------------------------+
string CConfluenceEngine::BreakdownText(void) const
  {
   string t = "";
   for(int i = 0; i < CONF_COMPONENTS; i++)
      t += StringFormat("%s %.0f/%.0f | ", m_items[i].name, m_items[i].bull, m_items[i].bear);
   return t;
  }

#endif // __XAUUSD_FTMO_CONFLUENCE_MQH__
//+------------------------------------------------------------------+
