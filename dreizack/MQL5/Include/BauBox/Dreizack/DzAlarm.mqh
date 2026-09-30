//+------------------------------------------------------------------+
//|                                                      DzAlarm.mqh |
//|        BauBox Dreizack - Alarm, ausschliesslich fuer die         |
//|        Rechtecke, die ueber die Alarmtasten gesetzt wurden       |
//|                                                                  |
//| Der Kern in einem Satz: geprueft werden nur Objekte, deren Name  |
//| mit DZ_PRE_ALARM beginnt. Ein von Hand gezogenes Rechteck heisst |
//| in MetaTrader "Rectangle 1234" und wird deshalb niemals geprueft |
//| - ebensowenig die Rechtecke von den Tasten ohne Alarm.           |
//|                                                                  |
//| Ausgeloest wird beim Eintritt in die Zone, nicht waehrend man    |
//| darin steht. Steht der Kurs beim Start schon in einer Zone,      |
//| gilt sie als bereits betreten und bleibt still, bis der Kurs     |
//| sie verlassen und erneut betreten hat.                           |
//+------------------------------------------------------------------+
#ifndef BAUBOX_DZ_ALARM_MQH
#define BAUBOX_DZ_ALARM_MQH

#include "DzTypes.mqh"
#include "DzUtil.mqh"

//--- Einstellungen
bool            g_alOn        = true;
ENUM_DZ_TRIGGER g_alTrigger   = DZ_TRIG_TOUCH;
bool            g_alTimeBox   = false;   // true: nur innerhalb der Zeitspanne des Rechtecks
bool            g_alRepeat    = true;    // true: jeder neue Eintritt meldet sich wieder
bool            g_alPopup     = true;
bool            g_alSound     = true;
string          g_alSoundFile = "alert2.wav";
bool            g_alPush      = false;
bool            g_alMail      = false;
bool            g_alMark      = true;    // ausgeloeste Zone gestrichelt zeichnen
int             g_alCooldown  = 60;      // Sperrzeit je Zone in Sekunden

//--- Zustand je Alarmrechteck
string   g_alName[];
bool     g_alInside[];
bool     g_alFired[];
datetime g_alLast[];
ulong    g_alScanTick = 0;

//--- Platz fuer einen weiteren Eintrag schaffen
void DzAlarmPush(const string name, const bool inside)
  {
   int n = ArraySize(g_alName);
   ArrayResize(g_alName,   n + 1);
   ArrayResize(g_alInside, n + 1);
   ArrayResize(g_alFired,  n + 1);
   ArrayResize(g_alLast,   n + 1);
   g_alName[n]   = name;
   g_alInside[n] = inside;
   g_alFired[n]  = false;
   g_alLast[n]   = 0;
  }

//--- Eintrag suchen
int DzAlarmFind(const string name)
  {
   for(int i = ArraySize(g_alName) - 1; i >= 0; i--)
      if(g_alName[i] == name)
         return i;
   return -1;
  }

//+------------------------------------------------------------------+
//| Preisband eines Rechtecks                                        |
//+------------------------------------------------------------------+
bool DzAlarmBand(const string name, double &lo, double &hi,
                 datetime &tFrom, datetime &tTo)
  {
   if(ObjectFind(0, name) < 0)
      return false;
   if(ObjectGetInteger(0, name, OBJPROP_TYPE) != OBJ_RECTANGLE)
      return false;

   double p1 = ObjectGetDouble(0, name, OBJPROP_PRICE, 0);
   double p2 = ObjectGetDouble(0, name, OBJPROP_PRICE, 1);
   datetime t1 = (datetime)ObjectGetInteger(0, name, OBJPROP_TIME, 0);
   datetime t2 = (datetime)ObjectGetInteger(0, name, OBJPROP_TIME, 1);

   lo = MathMin(p1, p2);
   hi = MathMax(p1, p2);
   tFrom = (t1 < t2 ? t1 : t2);
   tTo   = (t1 < t2 ? t2 : t1);
   return (hi > lo);
  }

//--- darf die Zone zu dieser Zeit ueberhaupt melden
bool DzAlarmTimeOk(const datetime now, const datetime tFrom, const datetime tTo)
  {
   if(now < tFrom)
      return false;                       // Zone liegt noch in der Zukunft
   if(g_alTimeBox && now > tTo)
      return false;                       // Zeitfenster ist abgelaufen
   return true;
  }

//+------------------------------------------------------------------+
//| Liste der Alarmzonen mit dem Chart abgleichen.                   |
//|                                                                  |
//| Neue Zonen werden mit dem aktuellen Stand angelegt, ohne zu      |
//| melden. Verschwundene Zonen fallen aus der Liste.                |
//+------------------------------------------------------------------+
void DzAlarmSync(const double price)
  {
   g_alScanTick = GetTickCount64();

   //--- verschwundene Eintraege entfernen
   for(int i = ArraySize(g_alName) - 1; i >= 0; i--)
     {
      if(ObjectFind(0, g_alName[i]) >= 0)
         continue;
      int last = ArraySize(g_alName) - 1;
      g_alName[i]   = g_alName[last];
      g_alInside[i] = g_alInside[last];
      g_alFired[i]  = g_alFired[last];
      g_alLast[i]   = g_alLast[last];
      ArrayResize(g_alName,   last);
      ArrayResize(g_alInside, last);
      ArrayResize(g_alFired,  last);
      ArrayResize(g_alLast,   last);
     }

   //--- neue Eintraege aufnehmen
   int len = StringLen(DZ_PRE_ALARM);
   for(int i = ObjectsTotal(0, -1, -1) - 1; i >= 0; i--)
     {
      string nm = ObjectName(0, i, -1, -1);
      if(StringSubstr(nm, 0, len) != DZ_PRE_ALARM)
         continue;
      if(DzAlarmFind(nm) >= 0)
         continue;

      double lo, hi;
      datetime tf, tt;
      bool inside = false;
      if(DzAlarmBand(nm, lo, hi, tf, tt))
         inside = (price >= lo && price <= hi);
      DzAlarmPush(nm, inside);            // bewusst stumm angelegt
     }
  }

//+------------------------------------------------------------------+
//| Meldung abschicken                                               |
//+------------------------------------------------------------------+
void DzAlarmFire(const string name, const double price,
                 const double lo, const double hi)
  {
   string note = ObjectGetString(0, name, OBJPROP_TEXT);
   string what = (note == "" ? name : note);

   string msg = StringFormat("%s %s: Kurs %s in Alarmzone %s  (%s - %s)",
                             _Symbol, DzPeriodName(_Period),
                             DoubleToString(price, _Digits), what,
                             DoubleToString(lo, _Digits),
                             DoubleToString(hi, _Digits));

   if(g_alPopup)
      Alert(msg);
   else
      Print(msg);

   if(g_alSound && g_alSoundFile != "")
      PlaySound(g_alSoundFile);

   if(g_alPush && !SendNotification(msg))
      PrintFormat("Dreizack: Push konnte nicht gesendet werden (%d). "
                  "In den Einstellungen unter Mitteilungen die MetaQuotes-ID eintragen.",
                  GetLastError());

   if(g_alMail && !SendMail("Dreizack Alarm", msg))
      PrintFormat("Dreizack: E-Mail konnte nicht gesendet werden (%d). "
                  "In den Einstellungen unter E-Mail den Versand einrichten.",
                  GetLastError());

   if(g_alMark)
     {
      ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DOT);
      ObjectSetString(0, name, OBJPROP_TOOLTIP,
                      "Dreizack: Alarmzone, bereits ausgeloest");
     }
  }

//+------------------------------------------------------------------+
//| Alle Alarmzonen pruefen.                                         |
//|                                                                  |
//| newBar sagt, ob seit dem letzten Aufruf eine Kerze geschlossen   |
//| hat. Nur dann wird im Modus Kerzenschluss geprueft.              |
//+------------------------------------------------------------------+
void DzAlarmCheck(const bool newBar)
  {
   if(!g_alOn)
      return;

   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(price <= 0.0)
      price = iClose(_Symbol, _Period, 0);
   if(price <= 0.0)
      return;

   //--- Bei Kerzenschluss zaehlt der Schlusskurs der eben beendeten Kerze
   bool evaluate = true;
   double testPrice = price;
   if(g_alTrigger == DZ_TRIG_CLOSE)
     {
      evaluate = newBar;
      if(evaluate)
        {
         testPrice = iClose(_Symbol, _Period, 1);
         if(testPrice <= 0.0)
            evaluate = false;
        }
     }

   //--- Liste hoechstens einmal je Sekunde neu einlesen
   if(g_alScanTick == 0 || GetTickCount64() - g_alScanTick > 1000)
      DzAlarmSync(testPrice);

   if(!evaluate)
      return;

   datetime now = TimeTradeServer();
   if(now <= 0)
      now = TimeCurrent();

   for(int i = ArraySize(g_alName) - 1; i >= 0; i--)
     {
      double lo, hi;
      datetime tf, tt;
      if(!DzAlarmBand(g_alName[i], lo, hi, tf, tt))
         continue;

      bool inside = (testPrice >= lo && testPrice <= hi);
      bool was    = g_alInside[i];
      g_alInside[i] = inside;

      if(!inside)
        {
         //--- Zone verlassen: sie darf beim naechsten Eintritt wieder melden
         if(g_alRepeat)
            g_alFired[i] = false;
         continue;
        }

      if(was)                              // war schon drin, kein neuer Eintritt
         continue;
      if(g_alFired[i])                     // einmalige Zone hat ihren Ruf verbraucht
         continue;
      if(!DzAlarmTimeOk(now, tf, tt))
         continue;
      if(g_alCooldown > 0 && g_alLast[i] > 0 &&
         ((long)now - (long)g_alLast[i]) < (long)g_alCooldown)
         continue;

      g_alFired[i] = true;
      g_alLast[i]  = now;
      DzAlarmFire(g_alName[i], testPrice, lo, hi);
     }
  }

//--- Liste leeren, z. B. beim Neustart des Indikators
void DzAlarmReset(void)
  {
   ArrayFree(g_alName);
   ArrayFree(g_alInside);
   ArrayFree(g_alFired);
   ArrayFree(g_alLast);
   g_alScanTick = 0;
  }

#endif // BAUBOX_DZ_ALARM_MQH
//+------------------------------------------------------------------+
