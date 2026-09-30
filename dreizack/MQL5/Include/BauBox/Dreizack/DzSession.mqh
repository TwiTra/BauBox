//+------------------------------------------------------------------+
//|                                                    DzSession.mqh |
//|            BauBox Dreizack - Kerzenrestzeit und Handelssessions  |
//+------------------------------------------------------------------+
#ifndef BAUBOX_DZ_SESSION_MQH
#define BAUBOX_DZ_SESSION_MQH

#include "DzTypes.mqh"
#include "DzUtil.mqh"

//--- Die vier Sessions, bereits auf Serverzeit umgerechnet
DzSessionDef g_dzSess[];
int          g_dzGmtOffsetSec = 0;   // Server minus GMT, in Sekunden

//+------------------------------------------------------------------+
//| Serverzeit. TimeTradeServer laeuft auch dann weiter, wenn gerade |
//| keine Ticks kommen - genau das braucht ein Countdown.            |
//+------------------------------------------------------------------+
datetime DzServerNow(void)
  {
   datetime t = TimeTradeServer();
   if(t <= 0)
      t = TimeCurrent();
   return t;
  }

//+------------------------------------------------------------------+
//| Abstand des Brokerservers zu GMT.                                |
//|                                                                  |
//| Ermittelt wird er aus Serverzeit minus GMT, gerundet auf halbe   |
//| Stunden. Das setzt eine richtig gestellte Uhr am Rechner voraus; |
//| wem das zu wackelig ist, der traegt den Wert von Hand ein.       |
//+------------------------------------------------------------------+
int DzDetectGmtOffsetSec(void)
  {
   datetime srv = DzServerNow();
   datetime gmt = TimeGMT();
   if(srv <= 0 || gmt <= 0)
      return 0;
   //--- ueber long, damit ein Server westlich von GMT nicht ueberlaeuft
   double diff = (double)((long)srv - (long)gmt);
   return (int)(MathRound(diff / 1800.0) * 1800.0);
  }

//+------------------------------------------------------------------+
//| "08:00-17:00" zerlegen. Liefert false, wenn der Text nicht passt |
//+------------------------------------------------------------------+
bool DzParseSpan(const string spec, int &fromMin, int &toMin)
  {
   fromMin = 0;
   toMin   = 0;
   string s = spec;
   StringTrimLeft(s);
   StringTrimRight(s);
   if(StringLen(s) < 9)
      return false;

   int dash = StringFind(s, "-");
   if(dash < 0)
      return false;

   string a = StringSubstr(s, 0, dash);
   string b = StringSubstr(s, dash + 1);
   StringTrimLeft(a); StringTrimRight(a);
   StringTrimLeft(b); StringTrimRight(b);

   int ca = StringFind(a, ":");
   int cb = StringFind(b, ":");
   if(ca < 0 || cb < 0)
      return false;

   int ah = (int)StringToInteger(StringSubstr(a, 0, ca));
   int am = (int)StringToInteger(StringSubstr(a, ca + 1));
   int bh = (int)StringToInteger(StringSubstr(b, 0, cb));
   int bm = (int)StringToInteger(StringSubstr(b, cb + 1));

   if(ah < 0 || ah > 23 || bh < 0 || bh > 23)
      return false;
   if(am < 0 || am > 59 || bm < 0 || bm > 59)
      return false;

   fromMin = ah * 60 + am;
   toMin   = bh * 60 + bm;
   return true;
  }

//--- Minuten in den Bereich 0..1439 zwingen
int DzWrapMin(const int m)
  {
   return ((m % 1440) + 1440) % 1440;
  }

//+------------------------------------------------------------------+
//| Eine Session in die Liste aufnehmen. Die Zeiten kommen in GMT    |
//| herein und werden hier auf Serverzeit geschoben.                 |
//+------------------------------------------------------------------+
void DzSessionAdd(const string name, const string spanGmt, const color col, const bool use)
  {
   int from, to;
   if(!DzParseSpan(spanGmt, from, to))
     {
      if(use)
         PrintFormat("Dreizack: Zeitspanne \"%s\" fuer %s ist unlesbar, erwartet wird HH:MM-HH:MM",
                     spanGmt, name);
      return;
     }

   int off = g_dzGmtOffsetSec / 60;
   int n   = ArraySize(g_dzSess);
   ArrayResize(g_dzSess, n + 1);
   g_dzSess[n].name = name;
   g_dzSess[n].from = DzWrapMin(from + off);
   g_dzSess[n].to   = DzWrapMin(to   + off);
   g_dzSess[n].col  = col;
   g_dzSess[n].use  = use;
  }

//--- Liste leeren und Offset neu bestimmen
void DzSessionsReset(const int manualOffsetHours, const bool automatic)
  {
   ArrayFree(g_dzSess);
   g_dzGmtOffsetSec = (automatic ? DzDetectGmtOffsetSec() : manualOffsetHours * 3600);
  }

//+------------------------------------------------------------------+
//| Minuten seit Mitternacht aus einem Zeitstempel                   |
//+------------------------------------------------------------------+
int DzMinuteOfDay(const datetime t)
  {
   MqlDateTime d;
   TimeToStruct(t, d);
   return d.hour * 60 + d.min;
  }

//+------------------------------------------------------------------+
//| Liegt "now" in der Spanne? Spannen ueber Mitternacht inbegriffen |
//+------------------------------------------------------------------+
bool DzInSpan(const int now, const int from, const int to)
  {
   if(from == to)
      return false;                       // leere Spanne
   if(from < to)
      return (now >= from && now < to);
   return (now >= from || now < to);      // laeuft ueber Mitternacht
  }

//--- Minuten, die seit dem Start vergangen sind
int DzSinceStart(const int now, const int from)
  {
   int d = now - from;
   return (d < 0 ? d + 1440 : d);
  }

//--- Minuten bis zum naechsten Start
int DzUntilStart(const int now, const int from)
  {
   int d = from - now;
   return (d < 0 ? d + 1440 : d);
  }

//+------------------------------------------------------------------+
//| Zustand der Sessions fuer das Fenster oben rechts.               |
//|                                                                  |
//| head  Name der laufenden Session, bei Ueberschneidung beide      |
//| sub   Spanne dieser Session in Serverzeit, z. B. "10:00 - 19:00" |
//| col   Farbe der fuehrenden Session                               |
//|                                                                  |
//| Laeuft gerade keine, steht in head "Pause" und in sub, welche    |
//| Session als naechste oeffnet und in wie vielen Stunden.          |
//+------------------------------------------------------------------+
void DzSessionState(const datetime serverNow, string &head, string &sub, color &col)
  {
   int total = ArraySize(g_dzSess);
   int now   = DzMinuteOfDay(serverNow);

   int lead = -1, second = -1, leadAge = 99999;
   for(int i = 0; i < total; i++)
     {
      if(!g_dzSess[i].use)
         continue;
      if(!DzInSpan(now, g_dzSess[i].from, g_dzSess[i].to))
         continue;
      int age = DzSinceStart(now, g_dzSess[i].from);
      if(age < leadAge)                   // die zuletzt geoeffnete fuehrt
        {
         second  = lead;
         lead    = i;
         leadAge = age;
        }
      else
         if(second < 0)
            second = i;
     }

   if(lead >= 0)
     {
      head = g_dzSess[lead].name;
      if(second >= 0)
         head += " + " + g_dzSess[second].name;
      sub = DzHhMm(g_dzSess[lead].from) + " - " + DzHhMm(g_dzSess[lead].to);
      col = g_dzSess[lead].col;
      return;
     }

   //--- nichts offen: die naechste Eroeffnung ansagen
   int next = -1, wait = 99999;
   for(int i = 0; i < total; i++)
     {
      if(!g_dzSess[i].use)
         continue;
      int d = DzUntilStart(now, g_dzSess[i].from);
      if(d < wait)
        {
         wait = d;
         next = i;
        }
     }

   head = "Pause";
   col  = clrSilver;
   if(next >= 0)
     {
      sub = StringFormat("%s in %02d:%02d", g_dzSess[next].name, wait / 60, wait % 60);
      col = g_dzSess[next].col;
     }
   else
      sub = "keine Session gesetzt";
  }

//+------------------------------------------------------------------+
//| Restzeit der laufenden Kerze in Sekunden                         |
//+------------------------------------------------------------------+
long DzCandleLeft(void)
  {
   long per = (long)PeriodSeconds(_Period);
   if(per <= 0)
      return 0;

   datetime t0 = iTime(_Symbol, _Period, 0);
   if(t0 <= 0)
      return 0;

   long left = per - ((long)DzServerNow() - (long)t0);
   if(left < 0)
      left = 0;
   if(left > per)
      left = per;
   return left;
  }

#endif // BAUBOX_DZ_SESSION_MQH
//+------------------------------------------------------------------+
