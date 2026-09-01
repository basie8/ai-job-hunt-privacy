//+------------------------------------------------------------------+
//|                                                       Logger.mqh |
//|   Structured console / journal logging so the user can follow    |
//|   the agent's live reasoning bar by bar.                         |
//+------------------------------------------------------------------+
#ifndef __SMC_LOGGER_MQH__
#define __SMC_LOGGER_MQH__

#include "Defs.mqh"

#define LOG_ERROR   0
#define LOG_WARN    1
#define LOG_INFO    2
#define LOG_DECIDE  3
#define LOG_DEBUG   4

class CLogger
  {
private:
   int               m_level;
   bool              m_to_file;
   int               m_fh;
   string            m_file;

   string            Tag(const int lvl)
     {
      switch(lvl)
        {
         case LOG_ERROR:  return("ERR  ");
         case LOG_WARN:   return("WARN ");
         case LOG_INFO:   return("INFO ");
         case LOG_DECIDE: return("THINK");
         case LOG_DEBUG:  return("DEBUG");
        }
      return("     ");
     }

public:
                     CLogger(void): m_level(LOG_DECIDE), m_to_file(false), m_fh(INVALID_HANDLE), m_file("") {}
                    ~CLogger(void) { Close(); }

   void              SetLevel(const int lvl) { m_level=lvl; }
   int               Level(void) const { return(m_level); }

   bool              OpenFile(const string name)
     {
      m_file=name;
      m_fh=FileOpen(name,FILE_WRITE|FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(m_fh==INVALID_HANDLE) { m_to_file=false; return(false); }
      FileSeek(m_fh,0,SEEK_END);
      m_to_file=true;
      return(true);
     }

   void              Close(void)
     {
      if(m_fh!=INVALID_HANDLE) { FileClose(m_fh); m_fh=INVALID_HANDLE; }
      m_to_file=false;
     }

   void              Write(const int lvl,const string msg)
     {
      if(lvl>m_level) return;
      string line=StringFormat("[%s] %s | %s",TimeToString(TimeCurrent(),TIME_DATE|TIME_MINUTES|TIME_SECONDS),Tag(lvl),msg);
      Print(line);
      if(m_to_file && m_fh!=INVALID_HANDLE)
        {
         FileWrite(m_fh,line);
         FileFlush(m_fh);
        }
     }

   void              Err(const string m)    { Write(LOG_ERROR,m);  }
   void              Warn(const string m)   { Write(LOG_WARN,m);   }
   void              Info(const string m)   { Write(LOG_INFO,m);   }
   void              Think(const string m)  { Write(LOG_DECIDE,m); }
   void              Debug(const string m)  { Write(LOG_DEBUG,m);  }

   void              Rule(const string title)
     {
      Write(LOG_DECIDE,"-------------------------------------------------------------");
      Write(LOG_DECIDE,title);
     }
  };

#endif // __SMC_LOGGER_MQH__
