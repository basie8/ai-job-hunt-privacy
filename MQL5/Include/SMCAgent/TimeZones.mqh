//+------------------------------------------------------------------+
//|                                                    TimeZones.mqh |
//|                                                                  |
//|  Exchange-local session timing without a network dependency.     |
//|                                                                  |
//|  Killzones are properties of an exchange, not of GMT. The London |
//|  open is 08:00 London local all year; the New York cash open is  |
//|  09:30 New York local all year. Expressed in GMT they move by an |
//|  hour twice a year, and the two regions do not switch on the same|
//|  date, so for two to three weeks in spring and one in autumn the |
//|  usual "fixed GMT window" is simply wrong.                       |
//|                                                                  |
//|  The transition rules are legislated and deterministic, so they  |
//|  are computed here rather than fetched:                          |
//|                                                                  |
//|    America/New_York  UTC-5 (EST) / UTC-4 (EDT)                   |
//|        starts  second Sunday in March, 02:00 EST = 07:00 UTC     |
//|        ends    first Sunday in November, 02:00 EDT = 06:00 UTC   |
//|        (Energy Policy Act 2005, in force since 2007)             |
//|                                                                  |
//|    Europe/London     UTC+0 (GMT)  / UTC+1 (BST)                  |
//|        starts  last Sunday in March, 01:00 UTC                   |
//|        ends    last Sunday in October, 01:00 UTC                 |
//|        (EU Directive 2000/84/EC, still in force)                 |
//|                                                                  |
//|  SmcTimezoneSelfTest() asserts these against known transition    |
//|  dates at start-up, so a rule that ever changes fails loudly     |
//|  instead of silently shifting every session window.              |
//+------------------------------------------------------------------+
#ifndef __SMC_TIMEZONES_MQH__
#define __SMC_TIMEZONES_MQH__

#include "Defs.mqh"

#define TZ_NY      0      // America/New_York
#define TZ_LONDON  1      // Europe/London

//+------------------------------------------------------------------+
//| Calendar helpers. Every datetime here is treated as UTC seconds. |
//+------------------------------------------------------------------+
int SmcDaysInMonth(const int y,const int m)
  {
   if(m<1 || m>12) return(30);
   if(m==2)
     {
      bool leap=((y%4==0 && y%100!=0) || (y%400==0));
      return(leap?29:28);
     }
   if(m==4 || m==6 || m==9 || m==11) return(30);
   return(31);
  }

datetime SmcMakeUtc(const int y,const int mo,const int d,const int h,const int mi=0)
  {
   MqlDateTime t;
   t.year=y; t.mon=mo; t.day=d;
   t.hour=h; t.min=mi; t.sec=0;
   t.day_of_week=0; t.day_of_year=0;
   return(StructToTime(t));
  }

int SmcDowOf(const datetime t)
  {
   MqlDateTime d;
   TimeToStruct(t,d);
   return(d.day_of_week);          // 0 = Sunday
  }

//--- nth (1-based) Sunday of a month, at a given UTC hour
datetime SmcNthSundayUtc(const int y,const int mo,const int nth,const int hour_utc)
  {
   datetime first=SmcMakeUtc(y,mo,1,hour_utc);
   int dow=SmcDowOf(first);
   int day=1+((7-dow)%7)+(nth-1)*7;
   if(day>SmcDaysInMonth(y,mo)) day-=7;
   return(SmcMakeUtc(y,mo,day,hour_utc));
  }

//--- last Sunday of a month, at a given UTC hour
datetime SmcLastSundayUtc(const int y,const int mo,const int hour_utc)
  {
   int dim=SmcDaysInMonth(y,mo);
   datetime last=SmcMakeUtc(y,mo,dim,hour_utc);
   int day=dim-SmcDowOf(last);
   return(SmcMakeUtc(y,mo,day,hour_utc));
  }

//+------------------------------------------------------------------+
//| Daylight saving state                                            |
//+------------------------------------------------------------------+
bool SmcIsUsDst(const datetime utc)
  {
   MqlDateTime d;
   TimeToStruct(utc,d);
   datetime start=SmcNthSundayUtc(d.year,3,2,7);    // 02:00 EST -> 07:00 UTC
   datetime end  =SmcNthSundayUtc(d.year,11,1,6);   // 02:00 EDT -> 06:00 UTC
   return(utc>=start && utc<end);
  }

bool SmcIsEuDst(const datetime utc)
  {
   MqlDateTime d;
   TimeToStruct(utc,d);
   datetime start=SmcLastSundayUtc(d.year,3,1);     // 01:00 UTC
   datetime end  =SmcLastSundayUtc(d.year,10,1);    // 01:00 UTC
   return(utc>=start && utc<end);
  }

//--- offset of the exchange zone from UTC, in hours, at this instant
int SmcZoneOffset(const int zone,const datetime utc)
  {
   if(zone==TZ_NY) return(SmcIsUsDst(utc)?-4:-5);
   return(SmcIsEuDst(utc)?1:0);
  }

string SmcZoneName(const int zone)
  { return(zone==TZ_NY?"New York":"London"); }

string SmcZoneAbbr(const int zone,const datetime utc)
  {
   if(zone==TZ_NY) return(SmcIsUsDst(utc)?"EDT":"EST");
   return(SmcIsEuDst(utc)?"BST":"GMT");
  }

//+------------------------------------------------------------------+
//| Conversions. All arithmetic goes through long, because a negative |
//| offset cast straight to datetime is not obviously correct.        |
//+------------------------------------------------------------------+
datetime SmcShift(const datetime t,const long seconds)
  { return((datetime)((long)t+seconds)); }

datetime SmcServerToUtc(const datetime server_time,const int gmt_offset)
  { return(SmcShift(server_time,-(long)gmt_offset*3600)); }

datetime SmcUtcToServer(const datetime utc,const int gmt_offset)
  { return(SmcShift(utc,(long)gmt_offset*3600)); }

datetime SmcUtcToZone(const int zone,const datetime utc)
  { return(SmcShift(utc,(long)SmcZoneOffset(zone,utc)*3600)); }

//--- local wall-clock time in that zone -> UTC
datetime SmcZoneToUtc(const int zone,const datetime local_wall)
  {
   int std=(zone==TZ_NY?-5:0);
   datetime guess=SmcShift(local_wall,-(long)std*3600);
   int off=SmcZoneOffset(zone,guess);
   datetime utc=SmcShift(local_wall,-(long)off*3600);
   int off2=SmcZoneOffset(zone,utc);
   if(off2!=off) utc=SmcShift(local_wall,-(long)off2*3600);
   return(utc);
  }

//--- hour of day (with minutes as a fraction) in the exchange zone
double SmcZoneHourF(const int zone,const datetime utc)
  {
   MqlDateTime d;
   TimeToStruct(SmcUtcToZone(zone,utc),d);
   return(d.hour+d.min/60.0);
  }

int SmcZoneDow(const int zone,const datetime utc)
  { return(SmcDowOf(SmcUtcToZone(zone,utc))); }

//--- midnight of the exchange-local day that contains this instant
datetime SmcZoneDayStart(const int zone,const datetime utc)
  { return(SmcDayStart(SmcUtcToZone(zone,utc))); }

//--- an exchange-local window [from_h,to_h) on a local day -> server time
void SmcZoneWindowToServer(const int zone,const datetime local_day_start,
                           const double from_h,const double to_h,const int gmt_offset,
                           datetime &t1,datetime &t2)
  {
   datetime l1=SmcShift(local_day_start,(long)(from_h*3600.0));
   datetime l2=SmcShift(local_day_start,(long)(to_h*3600.0));
   t1=SmcUtcToServer(SmcZoneToUtc(zone,l1),gmt_offset);
   t2=SmcUtcToServer(SmcZoneToUtc(zone,l2),gmt_offset);
  }

//+------------------------------------------------------------------+
//| Self test against known transitions.                             |
//| Returns true when every assertion holds; report carries the       |
//| detail either way.                                                |
//+------------------------------------------------------------------+
bool SmcTzCheck(const bool got,const bool want,const string what,string &report,int &fails)
  {
   if(got==want) return(true);
   report+=StringFormat("FAIL %s (got %s, expected %s); ",what,(got?"DST":"standard"),(want?"DST":"standard"));
   fails++;
   return(false);
  }

bool SmcTimezoneSelfTest(string &report)
  {
   report="";
   int fails=0;

   //--- United States 2026: 08 Mar -> 01 Nov
   SmcTzCheck(SmcIsUsDst(SmcMakeUtc(2026,3,8,6,59)),false,"US 2026-03-08 06:59 UTC",report,fails);
   SmcTzCheck(SmcIsUsDst(SmcMakeUtc(2026,3,8,7,0)), true, "US 2026-03-08 07:00 UTC",report,fails);
   SmcTzCheck(SmcIsUsDst(SmcMakeUtc(2026,11,1,5,59)),true,"US 2026-11-01 05:59 UTC",report,fails);
   SmcTzCheck(SmcIsUsDst(SmcMakeUtc(2026,11,1,6,0)),false,"US 2026-11-01 06:00 UTC",report,fails);
   //--- United States 2027: 14 Mar -> 07 Nov
   SmcTzCheck(SmcIsUsDst(SmcMakeUtc(2027,3,14,7,0)),true,"US 2027-03-14 07:00 UTC",report,fails);
   SmcTzCheck(SmcIsUsDst(SmcMakeUtc(2027,11,7,6,0)),false,"US 2027-11-07 06:00 UTC",report,fails);

   //--- Europe 2026: 29 Mar -> 25 Oct
   SmcTzCheck(SmcIsEuDst(SmcMakeUtc(2026,3,29,0,59)),false,"EU 2026-03-29 00:59 UTC",report,fails);
   SmcTzCheck(SmcIsEuDst(SmcMakeUtc(2026,3,29,1,0)), true, "EU 2026-03-29 01:00 UTC",report,fails);
   SmcTzCheck(SmcIsEuDst(SmcMakeUtc(2026,10,25,0,59)),true,"EU 2026-10-25 00:59 UTC",report,fails);
   SmcTzCheck(SmcIsEuDst(SmcMakeUtc(2026,10,25,1,0)),false,"EU 2026-10-25 01:00 UTC",report,fails);
   //--- Europe 2027: 28 Mar -> 31 Oct
   SmcTzCheck(SmcIsEuDst(SmcMakeUtc(2027,3,28,1,0)),true,"EU 2027-03-28 01:00 UTC",report,fails);
   SmcTzCheck(SmcIsEuDst(SmcMakeUtc(2027,10,31,1,0)),false,"EU 2027-10-31 01:00 UTC",report,fails);

   //--- the three week window where the two regions disagree:
   //--- 20 Mar 2026 13:30 UTC is 09:30 New York (EDT) and 13:30 London (GMT)
   datetime t=SmcMakeUtc(2026,3,20,13,30);
   if(MathAbs(SmcZoneHourF(TZ_NY,t)-9.5)>0.01)
     { report+="FAIL NY local on 2026-03-20 13:30 UTC; "; fails++; }
   if(MathAbs(SmcZoneHourF(TZ_LONDON,t)-13.5)>0.01)
     { report+="FAIL London local on 2026-03-20 13:30 UTC; "; fails++; }
   //--- deep summer: 14:30 UTC is 10:30 New York (EDT), 15:30 London (BST)
   t=SmcMakeUtc(2026,7,1,14,30);
   if(MathAbs(SmcZoneHourF(TZ_NY,t)-10.5)>0.01)
     { report+="FAIL NY local on 2026-07-01 14:30 UTC; "; fails++; }
   if(MathAbs(SmcZoneHourF(TZ_LONDON,t)-15.5)>0.01)
     { report+="FAIL London local on 2026-07-01 14:30 UTC; "; fails++; }
   //--- deep winter: 14:30 UTC is 09:30 New York (EST), 14:30 London (GMT)
   t=SmcMakeUtc(2026,1,15,14,30);
   if(MathAbs(SmcZoneHourF(TZ_NY,t)-9.5)>0.01)
     { report+="FAIL NY local on 2026-01-15 14:30 UTC; "; fails++; }
   //--- round trip: local wall clock -> UTC -> local
   t=SmcZoneToUtc(TZ_NY,SmcMakeUtc(2026,7,1,9,30));
   if(MathAbs(SmcZoneHourF(TZ_NY,t)-9.5)>0.01)
     { report+="FAIL NY round trip; "; fails++; }

   if(fails==0) report="all timezone assertions passed (US and EU transitions 2026-2027, cross-region mismatch window, round trip)";
   return(fails==0);
  }

#endif // __SMC_TIMEZONES_MQH__
