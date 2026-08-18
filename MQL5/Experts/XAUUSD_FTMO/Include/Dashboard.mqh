//+------------------------------------------------------------------+
//|                                                    Dashboard.mqh |
//|  "Aurum" console - an on-chart status panel for the XAUUSD EA.   |
//|                                                                  |
//|  Palette is metallic gold on warm near-black, chosen so it stays |
//|  readable over both a light and a dark chart background without  |
//|  competing with the candles.                                     |
//|                                                                  |
//|  Layout is a framed panel with a header bar, section headings,   |
//|  and two-column rows (label left, value right-aligned). Sections |
//|  can be collapsed from the header buttons; the collapse state is |
//|  owned by the caller so it survives a repaint.                   |
//+------------------------------------------------------------------+
#ifndef __XAUUSD_FTMO_DASHBOARD_MQH__
#define __XAUUSD_FTMO_DASHBOARD_MQH__

//--- version stamp. The EA checks for this, so copying a new .mq5
//--- next to a stale .mqh fails with one named error instead of forty.
#define XFC_V_DASHBOARD_2

#define DASH_PREFIX  "XFC_"
#define DASH_BTN_PARAMS  DASH_PREFIX "btn_params"
#define DASH_BTN_METRICS DASH_PREFIX "btn_metrics"

//--- Aurum palette -------------------------------------------------
#define AURUM_BG          C'16,14,11'      // warm near-black panel
#define AURUM_HEADER      C'34,28,18'      // header bar
#define AURUM_BORDER      C'176,141,44'    // struck gold edge
#define AURUM_GOLD        C'212,175,55'    // metallic gold - headings
#define AURUM_GOLD_BRIGHT C'255,214,92'    // highlight
#define AURUM_GOLD_DIM    C'138,114,48'    // separators
#define AURUM_TEXT        C'226,220,206'   // warm off-white - values
#define AURUM_LABEL       C'156,148,130'   // muted - row labels
#define AURUM_GOOD        C'118,196,124'   // green
#define AURUM_WARN        C'232,176,66'    // amber
#define AURUM_BAD         C'214,88,78'     // red

//+------------------------------------------------------------------+
class CDashboard
  {
private:
   long              m_chart;
   int               m_x;
   int               m_y;
   int               m_width;
   int               m_lineHeight;
   int               m_fontSize;
   string            m_font;
   int               m_line;            // current row index while drawing
   int               m_maxLineDrawn;    // high-water mark from the last frame
   bool              m_enabled;
   bool              m_buttonsBuilt;

   void              EnsureLabel(const string name, const int x, const int y,
                                 const int anchor, const int fontSize,
                                 const color clr, const string font);
   string            RowName(const int line, const string suffix);
   void              PurgeBelow(const int line);

public:
                     CDashboard(void);
                    ~CDashboard(void);

   void              Init(const bool enabled, const int x, const int y,
                          const int width, const int fontSize);

   //--- frame lifecycle
   void              Begin(void);
   void              End(void);

   //--- content
   void              Header(const string title, const string subtitle);
   void              Section(const string title);
   void              Row(const string label, const string value, const color valueColor = AURUM_TEXT);
   void              Banner(const string text, const color fg);

   //--- toggle buttons
   void              BuildButtons(const bool paramsOn, const bool metricsOn);
   bool              IsParamsButton(const string objectName) const { return (objectName == DASH_BTN_PARAMS); }
   bool              IsMetricsButton(const string objectName) const { return (objectName == DASH_BTN_METRICS); }

   void              Destroy(void);
  };

//+------------------------------------------------------------------+
CDashboard::CDashboard(void)
  {
   m_chart        = 0;
   m_x            = 12;
   m_y            = 22;
   m_width        = 360;
   m_fontSize     = 8;
   m_lineHeight   = 14;
   m_font         = "Consolas";
   m_line         = 0;
   m_maxLineDrawn = 0;
   m_enabled      = true;
   m_buttonsBuilt = false;
  }

//+------------------------------------------------------------------+
CDashboard::~CDashboard(void)
  {
   Destroy();
  }

//+------------------------------------------------------------------+
void CDashboard::Init(const bool enabled, const int x, const int y,
                      const int width, const int fontSize)
  {
   m_enabled    = enabled;
   m_x          = x;
   m_y          = y;
   m_width      = MathMax(240, width);
   m_fontSize   = MathMax(6, fontSize);
   m_lineHeight = m_fontSize + 6;
   m_chart      = ChartID();
   m_buttonsBuilt = false;

   Destroy();
  }

//+------------------------------------------------------------------+
string CDashboard::RowName(const int line, const string suffix)
  {
   return StringFormat("%s%s_%d", DASH_PREFIX, suffix, line);
  }

//+------------------------------------------------------------------+
void CDashboard::EnsureLabel(const string name, const int x, const int y,
                             const int anchor, const int fontSize,
                             const color clr, const string font)
  {
   if(ObjectFind(m_chart, name) < 0)
     {
      ObjectCreate(m_chart, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(m_chart, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(m_chart, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(m_chart, name, OBJPROP_SELECTED, false);
      ObjectSetInteger(m_chart, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(m_chart, name, OBJPROP_BACK, false);
      ObjectSetInteger(m_chart, name, OBJPROP_ZORDER, 10);
     }

   ObjectSetInteger(m_chart, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(m_chart, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(m_chart, name, OBJPROP_ANCHOR, anchor);
   ObjectSetInteger(m_chart, name, OBJPROP_FONTSIZE, fontSize);
   ObjectSetInteger(m_chart, name, OBJPROP_COLOR, clr);
   ObjectSetString(m_chart, name, OBJPROP_FONT, font);
  }

//+------------------------------------------------------------------+
//| Starts a frame. The background is sized from the previous        |
//| frame's row count so the panel never flickers between sizes.     |
//+------------------------------------------------------------------+
void CDashboard::Begin(void)
  {
   if(!m_enabled)
      return;

   m_line = 0;

   string bg = DASH_PREFIX "bg";

   if(ObjectFind(m_chart, bg) < 0)
     {
      ObjectCreate(m_chart, bg, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(m_chart, bg, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(m_chart, bg, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(m_chart, bg, OBJPROP_HIDDEN, true);
      ObjectSetInteger(m_chart, bg, OBJPROP_BACK, false);
      ObjectSetInteger(m_chart, bg, OBJPROP_ZORDER, 0);
      ObjectSetInteger(m_chart, bg, OBJPROP_BORDER_TYPE, BORDER_FLAT);
      ObjectSetInteger(m_chart, bg, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetInteger(m_chart, bg, OBJPROP_WIDTH, 1);
     }

   ObjectSetInteger(m_chart, bg, OBJPROP_XDISTANCE, m_x - 8);
   ObjectSetInteger(m_chart, bg, OBJPROP_YDISTANCE, m_y - 8);
   ObjectSetInteger(m_chart, bg, OBJPROP_XSIZE, m_width + 16);
   ObjectSetInteger(m_chart, bg, OBJPROP_BGCOLOR, AURUM_BG);
   ObjectSetInteger(m_chart, bg, OBJPROP_COLOR, AURUM_BORDER);

   //--- header bar behind the title row
   string hb = DASH_PREFIX "headerbar";
   if(ObjectFind(m_chart, hb) < 0)
     {
      ObjectCreate(m_chart, hb, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(m_chart, hb, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(m_chart, hb, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(m_chart, hb, OBJPROP_HIDDEN, true);
      ObjectSetInteger(m_chart, hb, OBJPROP_BACK, false);
      ObjectSetInteger(m_chart, hb, OBJPROP_ZORDER, 1);
      ObjectSetInteger(m_chart, hb, OBJPROP_BORDER_TYPE, BORDER_FLAT);
     }
   ObjectSetInteger(m_chart, hb, OBJPROP_XDISTANCE, m_x - 8);
   ObjectSetInteger(m_chart, hb, OBJPROP_YDISTANCE, m_y - 8);
   ObjectSetInteger(m_chart, hb, OBJPROP_XSIZE, m_width + 16);
   ObjectSetInteger(m_chart, hb, OBJPROP_YSIZE, m_lineHeight * 2 + 10);
   ObjectSetInteger(m_chart, hb, OBJPROP_BGCOLOR, AURUM_HEADER);
   ObjectSetInteger(m_chart, hb, OBJPROP_COLOR, AURUM_BORDER);
  }

//+------------------------------------------------------------------+
//| Deletes rows left over from a taller previous frame.             |
//+------------------------------------------------------------------+
void CDashboard::PurgeBelow(const int line)
  {
   for(int i = line; i < m_maxLineDrawn + 4; i++)
     {
      ObjectDelete(m_chart, RowName(i, "l"));
      ObjectDelete(m_chart, RowName(i, "v"));
     }
  }

//+------------------------------------------------------------------+
void CDashboard::End(void)
  {
   if(!m_enabled)
      return;

   PurgeBelow(m_line);

   // size the frame from the rows actually drawn THIS pass, so toggling a
   // section open resizes the panel immediately rather than a frame later
   int height = m_line * m_lineHeight + 18;
   ObjectSetInteger(m_chart, DASH_PREFIX "bg", OBJPROP_YSIZE, height);

   m_maxLineDrawn = m_line;
   ChartRedraw(m_chart);
  }

//+------------------------------------------------------------------+
void CDashboard::Header(const string title, const string subtitle)
  {
   if(!m_enabled)
      return;

   int y = m_y + m_line * m_lineHeight;
   EnsureLabel(RowName(m_line, "l"), m_x, y, ANCHOR_LEFT_UPPER,
               m_fontSize + 2, AURUM_GOLD_BRIGHT, "Consolas Bold");
   ObjectSetString(m_chart, RowName(m_line, "l"), OBJPROP_TEXT, title);
   ObjectDelete(m_chart, RowName(m_line, "v"));
   m_line++;

   y = m_y + m_line * m_lineHeight;
   EnsureLabel(RowName(m_line, "l"), m_x, y, ANCHOR_LEFT_UPPER,
               m_fontSize, AURUM_LABEL, m_font);
   ObjectSetString(m_chart, RowName(m_line, "l"), OBJPROP_TEXT, subtitle);
   ObjectDelete(m_chart, RowName(m_line, "v"));
   m_line++;
  }

//+------------------------------------------------------------------+
void CDashboard::Section(const string title)
  {
   if(!m_enabled)
      return;

   int y = m_y + m_line * m_lineHeight;

   EnsureLabel(RowName(m_line, "l"), m_x, y, ANCHOR_LEFT_UPPER,
               m_fontSize, AURUM_GOLD, "Consolas Bold");
   ObjectSetString(m_chart, RowName(m_line, "l"), OBJPROP_TEXT, title);

   // a rule of box-drawing characters carries the eye to the right edge
   EnsureLabel(RowName(m_line, "v"), m_x + m_width, y, ANCHOR_RIGHT_UPPER,
               m_fontSize, AURUM_GOLD_DIM, m_font);
   // approximate character count for the panel width at this font size,
   // so the rule reaches toward the right edge without overrunning it
   int cols = (m_width * 2) / (m_fontSize + 3);
   int pad  = cols - StringLen(title) - 2;
   string rule = "";
   for(int i = 0; i < pad && i < 80; i++)
      rule += "-";
   ObjectSetString(m_chart, RowName(m_line, "v"), OBJPROP_TEXT, rule);

   m_line++;
  }

//+------------------------------------------------------------------+
void CDashboard::Row(const string label, const string value, const color valueColor)
  {
   if(!m_enabled)
      return;

   int y = m_y + m_line * m_lineHeight;

   EnsureLabel(RowName(m_line, "l"), m_x, y, ANCHOR_LEFT_UPPER,
               m_fontSize, AURUM_LABEL, m_font);
   ObjectSetString(m_chart, RowName(m_line, "l"), OBJPROP_TEXT, label);

   EnsureLabel(RowName(m_line, "v"), m_x + m_width, y, ANCHOR_RIGHT_UPPER,
               m_fontSize, valueColor, m_font);
   ObjectSetString(m_chart, RowName(m_line, "v"), OBJPROP_TEXT, value);

   m_line++;
  }

//+------------------------------------------------------------------+
//| A full-width emphasised line - used for the status banner.       |
//+------------------------------------------------------------------+
void CDashboard::Banner(const string text, const color fg)
  {
   if(!m_enabled)
      return;

   int y = m_y + m_line * m_lineHeight;

   EnsureLabel(RowName(m_line, "l"), m_x, y, ANCHOR_LEFT_UPPER,
               m_fontSize + 1, fg, "Consolas Bold");
   ObjectSetString(m_chart, RowName(m_line, "l"), OBJPROP_TEXT, text);
   ObjectDelete(m_chart, RowName(m_line, "v"));

   m_line++;
  }

//+------------------------------------------------------------------+
//| Two small toggles pinned to the header bar.                      |
//+------------------------------------------------------------------+
void CDashboard::BuildButtons(const bool paramsOn, const bool metricsOn)
  {
   if(!m_enabled)
      return;

   string names[2]  = {DASH_BTN_PARAMS, DASH_BTN_METRICS};
   string texts[2]  = {"PARAMS", "STATS"};
   bool   states[2] = {paramsOn, metricsOn};

   int bw = 58;
   int bh = m_lineHeight + 2;

   for(int i = 0; i < 2; i++)
     {
      string n = names[i];
      if(ObjectFind(m_chart, n) < 0)
        {
         ObjectCreate(m_chart, n, OBJ_BUTTON, 0, 0, 0);
         ObjectSetInteger(m_chart, n, OBJPROP_CORNER, CORNER_LEFT_UPPER);
         ObjectSetInteger(m_chart, n, OBJPROP_HIDDEN, true);
         ObjectSetInteger(m_chart, n, OBJPROP_ZORDER, 20);
         ObjectSetString(m_chart, n, OBJPROP_FONT, m_font);
        }

      ObjectSetInteger(m_chart, n, OBJPROP_XDISTANCE, m_x + m_width - (2 - i) * (bw + 4) + 4);
      ObjectSetInteger(m_chart, n, OBJPROP_YDISTANCE, m_y - 4);
      ObjectSetInteger(m_chart, n, OBJPROP_XSIZE, bw);
      ObjectSetInteger(m_chart, n, OBJPROP_YSIZE, bh);
      ObjectSetInteger(m_chart, n, OBJPROP_FONTSIZE, m_fontSize - 1);
      ObjectSetInteger(m_chart, n, OBJPROP_BGCOLOR, (states[i] ? AURUM_GOLD_DIM : AURUM_HEADER));
      ObjectSetInteger(m_chart, n, OBJPROP_COLOR, (states[i] ? AURUM_GOLD_BRIGHT : AURUM_LABEL));
      ObjectSetInteger(m_chart, n, OBJPROP_BORDER_COLOR, AURUM_BORDER);
      ObjectSetInteger(m_chart, n, OBJPROP_STATE, false);
      ObjectSetString(m_chart, n, OBJPROP_TEXT, texts[i]);
     }

   m_buttonsBuilt = true;
  }

//+------------------------------------------------------------------+
void CDashboard::Destroy(void)
  {
   ObjectsDeleteAll(m_chart, DASH_PREFIX);
   m_maxLineDrawn = 0;
   m_buttonsBuilt = false;
   ChartRedraw(m_chart);
  }

#endif // __XAUUSD_FTMO_DASHBOARD_MQH__
//+------------------------------------------------------------------+
