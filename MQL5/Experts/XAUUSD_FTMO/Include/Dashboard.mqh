//+------------------------------------------------------------------+
//|                                                    Dashboard.mqh |
//|  Lightweight on-chart status panel.                              |
//|  Everything the EA is thinking, visible at a glance, so a live   |
//|  challenge account never has to be audited from the journal.     |
//+------------------------------------------------------------------+
#ifndef __XAUUSD_FTMO_DASHBOARD_MQH__
#define __XAUUSD_FTMO_DASHBOARD_MQH__

#define DASH_PREFIX "XFC_"

//+------------------------------------------------------------------+
class CDashboard
  {
private:
   long              m_chart;
   int               m_x;
   int               m_y;
   int               m_lineHeight;
   int               m_fontSize;
   string            m_font;
   int               m_lines;
   bool              m_enabled;

   void              Label(const int line, const string text, const color clr);

public:
                     CDashboard(void);
                    ~CDashboard(void);

   void              Init(const bool enabled, const int x, const int y, const int fontSize);
   void              Begin(void) { m_lines = 0; }
   void              Row(const string text, const color clr = clrGainsboro);
   void              Separator(void);
   void              Destroy(void);
  };

//+------------------------------------------------------------------+
CDashboard::CDashboard(void)
  {
   m_chart      = 0;
   m_x          = 12;
   m_y          = 24;
   m_lineHeight = 15;
   m_fontSize   = 9;
   m_font       = "Consolas";
   m_lines      = 0;
   m_enabled    = true;
  }

//+------------------------------------------------------------------+
CDashboard::~CDashboard(void)
  {
   Destroy();
  }

//+------------------------------------------------------------------+
void CDashboard::Init(const bool enabled, const int x, const int y, const int fontSize)
  {
   m_enabled  = enabled;
   m_x        = x;
   m_y        = y;
   m_fontSize = fontSize;
   m_lineHeight = fontSize + 6;
   m_chart    = ChartID();
   Destroy();
  }

//+------------------------------------------------------------------+
void CDashboard::Label(const int line, const string text, const color clr)
  {
   string name = StringFormat("%sline_%d", DASH_PREFIX, line);

   if(ObjectFind(m_chart, name) < 0)
     {
      ObjectCreate(m_chart, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(m_chart, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(m_chart, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(m_chart, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(m_chart, name, OBJPROP_BACK, false);
      ObjectSetString(m_chart, name, OBJPROP_FONT, m_font);
     }

   ObjectSetInteger(m_chart, name, OBJPROP_XDISTANCE, m_x);
   ObjectSetInteger(m_chart, name, OBJPROP_YDISTANCE, m_y + line * m_lineHeight);
   ObjectSetInteger(m_chart, name, OBJPROP_FONTSIZE, m_fontSize);
   ObjectSetInteger(m_chart, name, OBJPROP_COLOR, clr);
   ObjectSetString(m_chart, name, OBJPROP_TEXT, text);
  }

//+------------------------------------------------------------------+
void CDashboard::Row(const string text, const color clr)
  {
   if(!m_enabled)
      return;
   Label(m_lines, text, clr);
   m_lines++;
  }

//+------------------------------------------------------------------+
void CDashboard::Separator(void)
  {
   Row("--------------------------------------------", clrDimGray);
  }

//+------------------------------------------------------------------+
void CDashboard::Destroy(void)
  {
   ObjectsDeleteAll(m_chart, DASH_PREFIX);
   ChartRedraw(m_chart);
  }

#endif // __XAUUSD_FTMO_DASHBOARD_MQH__
//+------------------------------------------------------------------+
