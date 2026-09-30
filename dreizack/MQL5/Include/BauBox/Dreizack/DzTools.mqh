//+------------------------------------------------------------------+
//|                                                      DzTools.mqh |
//|          BauBox Dreizack - Rechtecke, Trendlinien, Dreizack      |
//+------------------------------------------------------------------+
#ifndef BAUBOX_DZ_TOOLS_MQH
#define BAUBOX_DZ_TOOLS_MQH

#include "DzTypes.mqh"
#include "DzUtil.mqh"
#include "DzPanel.mqh"

//--- Einstellungen der Rechtecke und Linien
bool   g_rcFill      = true;      // Flaeche fuellen
bool   g_rcBack      = true;      // hinter den Kerzen zeichnen
int    g_rcWidth     = 1;         // Randstaerke normal
int    g_rcAlarmWid  = 2;         // Randstaerke mit Alarm
int    g_lnWidth     = 1;         // Trendlinie
bool   g_lnRay       = false;     // Trendlinie nach rechts verlaengern

//--- Einstellungen des Dreizacks
ENUM_DZ_FORKMODE g_fkMode   = DZ_FORK_3CLICK;
ENUM_DZ_BASE     g_fkBase   = DZ_BASE_C;
ENUM_DZ_INFO     g_fkInfo   = DZ_INFO_BARS_POINTS;
double g_fkF1 = 1.0, g_fkF2 = 2.0, g_fkF3 = 3.0;
int    g_fkLevelBars = 60;        // Laenge der Stufen in Kerzen
int    g_fkFanBars   = 0;         // Vorlauf je Zinke, 0 = aus der Impulsdauer
bool   g_fkRay       = false;     // Stufen endlos nach rechts
int    g_fkLegWidth  = 1;
int    g_fkLevWidth  = 1;
bool   g_fkEmphasis  = true;      // Stufe 2 und 3 staerker zeichnen
bool   g_fkShowBox   = true;
bool   g_fkShowPrice = false;     // Preis neben die Stufennummer
color  g_fkBoxColor  = C'0,190,120';
color  g_fkLevColor  = clrNONE;   // clrNONE = Farbe des Dreizacks
int    g_fkAutoBars  = 30;        // Suchfenster im Ein-Klick-Betrieb
string g_fkFont      = "Arial";
int    g_fkFontSize  = 8;

//--- laufender Klickvorgang
ENUM_DZ_TOOL g_dzTool      = DZ_TOOL_NONE;
color        g_dzToolColor = clrNONE;
int          g_dzStep      = 0;
datetime     g_dzT[3];
double       g_dzP[3];

//+------------------------------------------------------------------+
//| Kerzennummer zu einem Zeitpunkt. 0 ist die laufende Kerze.       |
//+------------------------------------------------------------------+
int DzBarOf(const datetime t)
  {
   datetime now = iTime(_Symbol, _Period, 0);
   if(now <= 0)
      return 0;
   if(t >= now)
      return 0;

   int n = Bars(_Symbol, _Period, t, now);
   if(n <= 0)
      return 0;

   int last = Bars(_Symbol, _Period) - 1;
   int idx  = n - 1;
   if(last >= 0 && idx > last)
      idx = last;
   return idx;
  }

//+------------------------------------------------------------------+
//| Hoechster Hochpunkt im Bereich. Liefert die Kerzennummer.        |
//| Bewusst ueber CopyHigh statt iHighest, damit der Code auf jedem  |
//| Terminalstand uebersetzt.                                        |
//+------------------------------------------------------------------+
int DzHighestIdx(const int start, const int count)
  {
   if(count <= 0)
      return start;
   double buf[];
   ArraySetAsSeries(buf, false);
   int got = CopyHigh(_Symbol, _Period, start, count, buf);
   if(got <= 0)
      return start;
   //--- ohne AsSeries steht die aelteste Kerze auf Platz 0, die
   //--- juengste (Kerzennummer start) auf Platz got-1
   int k = ArrayMaximum(buf, 0, got);
   return start + (got - 1 - k);
  }

//--- tiefster Tiefpunkt im Bereich
int DzLowestIdx(const int start, const int count)
  {
   if(count <= 0)
      return start;
   double buf[];
   ArraySetAsSeries(buf, false);
   int got = CopyLow(_Symbol, _Period, start, count, buf);
   if(got <= 0)
      return start;
   int k = ArrayMinimum(buf, 0, got);
   return start + (got - 1 - k);
  }

//+------------------------------------------------------------------+
//| Rechteck anlegen. alarm entscheidet ueber das Namenspraefix und  |
//| damit darueber, ob das Alarmmodul das Rechteck spaeter ansieht.  |
//+------------------------------------------------------------------+
string DzMakeRect(const datetime t1, const double p1,
                  const datetime t2, const double p2,
                  const color col, const bool alarm)
  {
   string pre  = (alarm ? DZ_PRE_ALARM : DZ_PRE_RECT);
   string name = pre + IntegerToString(DzNextId(pre));

   if(!ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2))
     {
      PrintFormat("Dreizack: Rechteck %s liess sich nicht anlegen (%d)", name, GetLastError());
      return "";
     }

   ObjectSetInteger(0, name, OBJPROP_COLOR,      col);
   ObjectSetInteger(0, name, OBJPROP_STYLE,      STYLE_SOLID);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,      alarm ? g_rcAlarmWid : g_rcWidth);
   ObjectSetInteger(0, name, OBJPROP_FILL,       g_rcFill);
   ObjectSetInteger(0, name, OBJPROP_BACK,       g_rcBack);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTED,   false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,     false);
   ObjectSetString(0,  name, OBJPROP_TOOLTIP,
                   alarm ? "Dreizack: Rechteck MIT Alarm" : "Dreizack: Rechteck ohne Alarm");
   return name;
  }

//+------------------------------------------------------------------+
//| Trendlinie anlegen                                               |
//+------------------------------------------------------------------+
string DzMakeLine(const datetime t1, const double p1,
                  const datetime t2, const double p2, const color col)
  {
   string name = DZ_PRE_LINE + IntegerToString(DzNextId(DZ_PRE_LINE));

   if(!ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2))
     {
      PrintFormat("Dreizack: Trendlinie %s liess sich nicht anlegen (%d)", name, GetLastError());
      return "";
     }

   ObjectSetInteger(0, name, OBJPROP_COLOR,      col);
   ObjectSetInteger(0, name, OBJPROP_STYLE,      STYLE_SOLID);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,      g_lnWidth);
   ObjectSetInteger(0, name, OBJPROP_RAY_LEFT,   false);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT,  g_lnRay);
   ObjectSetInteger(0, name, OBJPROP_BACK,       false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTED,   false);
   ObjectSetString(0,  name, OBJPROP_TOOLTIP,    "Dreizack: Trendlinie");
   return name;
  }

//+------------------------------------------------------------------+
//|                        D R E I Z A C K                           |
//+------------------------------------------------------------------+

//--- Merkzettel eines Dreizacks: die drei Anker vor dem letzten Zug
void DzForkMetaSave(const long id, const DzAnchors &a)
  {
   string nm = DzForkPart(id, DZ_FORK_META);
   if(ObjectFind(0, nm) < 0)
     {
      ObjectCreate(0, nm, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, nm, OBJPROP_TIMEFRAMES, OBJ_NO_PERIODS);
      ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, nm, OBJPROP_HIDDEN,     true);
     }
   string s = IntegerToString((long)a.ta) + "|" + DoubleToString(a.pa, 8) + "|" +
              IntegerToString((long)a.tb) + "|" + DoubleToString(a.pb, 8) + "|" +
              IntegerToString((long)a.tc) + "|" + DoubleToString(a.pc, 8);
   ObjectSetString(0, nm, OBJPROP_TEXT, s);
  }

void DzForkMetaLoad(const long id, DzAnchors &a)
  {
   a.ok = false;
   string nm = DzForkPart(id, DZ_FORK_META);
   if(ObjectFind(0, nm) < 0)
      return;

   string f[];
   if(StringSplit(ObjectGetString(0, nm, OBJPROP_TEXT), '|', f) != 6)
      return;

   a.ta = (datetime)StringToInteger(f[0]);
   a.pa = StringToDouble(f[1]);
   a.tb = (datetime)StringToInteger(f[2]);
   a.pb = StringToDouble(f[3]);
   a.tc = (datetime)StringToInteger(f[4]);
   a.pc = StringToDouble(f[5]);
   a.ok = true;
  }

//--- Anker aus den beiden Schenkeln lesen
void DzForkRead(const long id, DzAnchors &a)
  {
   a.ok = false;
   string g1 = DzForkPart(id, DZ_FORK_LEG1);
   string g2 = DzForkPart(id, DZ_FORK_LEG2);
   if(ObjectFind(0, g1) < 0 || ObjectFind(0, g2) < 0)
      return;

   a.ta = (datetime)ObjectGetInteger(0, g1, OBJPROP_TIME,  0);
   a.pa = ObjectGetDouble(0, g1, OBJPROP_PRICE, 0);
   a.tb = (datetime)ObjectGetInteger(0, g1, OBJPROP_TIME,  1);
   a.pb = ObjectGetDouble(0, g1, OBJPROP_PRICE, 1);
   a.tc = (datetime)ObjectGetInteger(0, g2, OBJPROP_TIME,  1);
   a.pc = ObjectGetDouble(0, g2, OBJPROP_PRICE, 1);
   a.ok = true;
  }

//--- Farbe eines Dreizacks steckt im ersten Schenkel
color DzForkColor(const long id)
  {
   string g1 = DzForkPart(id, DZ_FORK_LEG1);
   if(ObjectFind(0, g1) < 0)
      return clrRed;
   return (color)ObjectGetInteger(0, g1, OBJPROP_COLOR);
  }

//--- Linie anlegen oder verschieben, ohne sie auswaehlbar zu machen
void DzSetSegment(const string name, const datetime t1, const double p1,
                  const datetime t2, const double p2, const color col,
                  const int width, const ENUM_LINE_STYLE style,
                  const bool ray, const bool selectable, const string tip)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2);
   else
     {
      ObjectSetInteger(0, name, OBJPROP_TIME,  0, t1);
      ObjectSetDouble(0,  name, OBJPROP_PRICE, 0, p1);
      ObjectSetInteger(0, name, OBJPROP_TIME,  1, t2);
      ObjectSetDouble(0,  name, OBJPROP_PRICE, 1, p2);
     }
   ObjectSetInteger(0, name, OBJPROP_COLOR,      col);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,      width);
   ObjectSetInteger(0, name, OBJPROP_STYLE,      style);
   ObjectSetInteger(0, name, OBJPROP_RAY_LEFT,   false);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT,  ray);
   ObjectSetInteger(0, name, OBJPROP_BACK,       false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, selectable);
   ObjectSetInteger(0, name, OBJPROP_SELECTED,   false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,     !selectable);
   ObjectSetString(0,  name, OBJPROP_TOOLTIP,    tip == "" ? "\n" : tip);
  }

//--- Text im Kursraster anlegen oder verschieben
void DzSetText(const string name, const datetime t, const double p,
               const string text, const color col, const int size,
               const ENUM_ANCHOR_POINT anchor)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TEXT, 0, t, p);
   else
     {
      ObjectSetInteger(0, name, OBJPROP_TIME,  0, t);
      ObjectSetDouble(0,  name, OBJPROP_PRICE, 0, p);
     }
   ObjectSetString(0,  name, OBJPROP_TEXT,       text);
   ObjectSetString(0,  name, OBJPROP_FONT,       g_fkFont);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE,   size);
   ObjectSetInteger(0, name, OBJPROP_COLOR,      col);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR,     anchor);
   ObjectSetInteger(0, name, OBJPROP_BACK,       false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTED,   false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,     true);
  }

//+------------------------------------------------------------------+
//| Dreizack aus seinen drei Ankern neu zeichnen.                    |
//|                                                                  |
//| Gemessen wird der Impuls A nach B. Von der Basis aus - das ist   |
//| gewoehnlich der Ruecklauf C - werden drei Stufen projiziert:     |
//|                                                                  |
//|   Stufe 1 = Basis + f1 * Impuls     erstes Ziel                  |
//|   Stufe 2 = Basis + f2 * Impuls     sicherer Bereich zum Mitnehmen|
//|   Stufe 3 = Basis + f3 * Impuls     Ende der Bewegung            |
//|                                                                  |
//| Die drei Zinken laufen faecherfoermig von der Basis zu den       |
//| Stufen, danach laeuft jede Stufe waagerecht nach rechts weiter.  |
//+------------------------------------------------------------------+
void DzForkDraw(const long id, const DzAnchors &a, const color col)
  {
   if(!a.ok)
      return;

   int    dir  = (a.pb >= a.pa ? 1 : -1);
   double imp  = MathAbs(a.pb - a.pa);
   double base = (g_fkBase == DZ_BASE_C ? a.pc : a.pb);

   double fac[3];
   fac[0] = g_fkF1;
   fac[1] = g_fkF2;
   fac[2] = g_fkF3;

   long per = (long)PeriodSeconds(_Period);
   if(per <= 0)
      per = 60;

   //--- Vorlauf einer Zinke. Ohne Vorgabe teilt sich die Impulsdauer
   //--- auf die drei Stufen auf, dann steht Stufe 3 eine Impulslaenge
   //--- rechts von der Basis.
   long span = (long)g_fkFanBars * per;
   if(g_fkFanBars <= 0)
     {
      //--- bewusst ueber long: datetime rechnet vorzeichenlos, und die
      //--- Spitze darf zeitlich auch vor dem Start liegen
      long dur = (long)a.tb - (long)a.ta;
      if(dur < 0)
         dur = -dur;
      span = (dur > 0 ? dur / 3 : per * 3);
     }
   if(span < per)
      span = per;

   color levCol = (g_fkLevColor == clrNONE ? col : g_fkLevColor);
   long  levLen = (long)g_fkLevelBars * per;
   if(levLen < per)
      levLen = per;

   //--- die beiden Schenkel: sie sind die Griffe zum Nachjustieren
   DzSetSegment(DzForkPart(id, DZ_FORK_LEG1), a.ta, a.pa, a.tb, a.pb, col,
                g_fkLegWidth, STYLE_SOLID, false, true,
                "Dreizack: Impuls (Start bis Spitze)");
   DzSetSegment(DzForkPart(id, DZ_FORK_LEG2), a.tb, a.pb, a.tc, a.pc, col,
                g_fkLegWidth, STYLE_SOLID, false, true,
                "Dreizack: Ruecklauf (Spitze bis Basis)");

   //--- Zinken und Stufen
   for(int i = 0; i < 3; i++)
     {
      double   lvl = base + dir * fac[i] * imp;
      datetime t0  = (datetime)((long)a.tc + span * (i + 1));
      datetime t1  = (datetime)((long)t0 + levLen);

      int   w  = g_fkLevWidth;
      ENUM_LINE_STYLE st = STYLE_SOLID;
      if(g_fkEmphasis)
        {
         //--- Stufe 1 ist nur Zwischenstation, 2 und 3 sind die Ziele
         if(i == 0) { w = g_fkLevWidth;     st = STYLE_DOT;   }
         if(i == 1) { w = g_fkLevWidth + 1; st = STYLE_SOLID; }
         if(i == 2) { w = g_fkLevWidth + 2; st = STYLE_SOLID; }
        }

      string num = IntegerToString(i + 1);

      DzSetSegment(DzForkPart(id, DZ_FORK_PRONG + num), a.tc, a.pc, t0, lvl, col,
                   g_fkLegWidth, STYLE_DOT, false, false, "\n");
      DzSetSegment(DzForkPart(id, DZ_FORK_LEVEL + num), t0, lvl, t1, lvl, levCol,
                   w, st, g_fkRay, false,
                   StringFormat("Dreizack Stufe %s: %s", num,
                                DoubleToString(lvl, _Digits)));

      string tag = num;
      if(g_fkShowPrice)
         tag += "  " + DoubleToString(lvl, _Digits);
      DzSetText(DzForkPart(id, DZ_FORK_TAG + num),
                (g_fkRay ? t0 : t1), lvl, "  " + tag, levCol,
                g_fkFontSize + (g_fkEmphasis && i >= 1 ? 1 : 0), ANCHOR_LEFT);
     }

   //--- gestrichelte Box um die Basis: von wo die Bewegung startete
   string bx = DzForkPart(id, DZ_FORK_BOX);
   if(g_fkShowBox)
     {
      datetime bt1 = (a.ta < a.tc ? a.ta : a.tc);
      datetime bt2 = (a.ta < a.tc ? a.tc : a.ta);
      double   bp1 = MathMin(a.pa, a.pc);
      double   bp2 = MathMax(a.pa, a.pc);

      if(ObjectFind(0, bx) < 0)
         ObjectCreate(0, bx, OBJ_RECTANGLE, 0, bt1, bp1, bt2, bp2);
      else
        {
         ObjectSetInteger(0, bx, OBJPROP_TIME,  0, bt1);
         ObjectSetDouble(0,  bx, OBJPROP_PRICE, 0, bp1);
         ObjectSetInteger(0, bx, OBJPROP_TIME,  1, bt2);
         ObjectSetDouble(0,  bx, OBJPROP_PRICE, 1, bp2);
        }
      ObjectSetInteger(0, bx, OBJPROP_COLOR,      g_fkBoxColor);
      ObjectSetInteger(0, bx, OBJPROP_STYLE,      STYLE_DASH);
      ObjectSetInteger(0, bx, OBJPROP_WIDTH,      1);
      ObjectSetInteger(0, bx, OBJPROP_FILL,       false);
      ObjectSetInteger(0, bx, OBJPROP_BACK,       true);
      ObjectSetInteger(0, bx, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, bx, OBJPROP_SELECTED,   false);
      ObjectSetInteger(0, bx, OBJPROP_HIDDEN,     true);
     }
   else
      DzDelete(bx);

   //--- Messtext an der Spitze
   string info = DzForkPart(id, DZ_FORK_INFO);
   if(g_fkInfo == DZ_INFO_OFF)
      DzDelete(info);
   else
     {
      string txt = "";
      double pts = DzPoints(imp);
      switch(g_fkInfo)
        {
         case DZ_INFO_BARS_POINTS:
           {
            int bars = (int)MathAbs(DzBarOf(a.ta) - DzBarOf(a.tb));
            txt = IntegerToString(bars) + "/" + DzGroup(pts);
            break;
           }
         case DZ_INFO_POINTS:
            txt = DzGroup(pts);
            break;
         case DZ_INFO_TARGET:
           {
            double reach = MathAbs(base + dir * fac[2] * imp - base);
            txt = DzGroup(pts) + "/" + DzGroup(DzPoints(reach));
            break;
           }
         default:
            break;
        }
      ENUM_ANCHOR_POINT infoAnchor = (dir > 0 ? ANCHOR_LOWER : ANCHOR_UPPER);
      DzSetText(info, a.tb, a.pb, txt, col, g_fkFontSize, infoAnchor);
     }

   DzForkMetaSave(id, a);
  }

//+------------------------------------------------------------------+
//| Neuen Dreizack anlegen                                           |
//+------------------------------------------------------------------+
long DzForkCreate(const DzAnchors &a, const color col)
  {
   if(!a.ok)
      return -1;
   long id = DzNextId(DZ_PRE_FORK);
   DzForkDraw(id, a, col);
   return id;
  }

//--- alle Teile eines Dreizacks entfernen
int DzForkDeleteGroup(const long id)
  {
   return DzDeletePrefix(DZ_PRE_FORK + IntegerToString(id) + "_");
  }

//+------------------------------------------------------------------+
//| Ein Schenkel wurde gezogen. Herausfinden, welcher Anker sich     |
//| bewegt hat, und den Dreizack daraus neu aufbauen.                |
//|                                                                  |
//| Der Punkt B steckt in beiden Schenkeln. Welcher der beiden der   |
//| neue ist, verraet der Vergleich mit dem Merkzettel.              |
//+------------------------------------------------------------------+
void DzForkOnDrag(const long id)
  {
   string g1 = DzForkPart(id, DZ_FORK_LEG1);
   string g2 = DzForkPart(id, DZ_FORK_LEG2);
   if(ObjectFind(0, g1) < 0 || ObjectFind(0, g2) < 0)
      return;

   datetime t1a = (datetime)ObjectGetInteger(0, g1, OBJPROP_TIME, 0);
   double   p1a = ObjectGetDouble(0, g1, OBJPROP_PRICE, 0);
   datetime t1b = (datetime)ObjectGetInteger(0, g1, OBJPROP_TIME, 1);
   double   p1b = ObjectGetDouble(0, g1, OBJPROP_PRICE, 1);
   datetime t2b = (datetime)ObjectGetInteger(0, g2, OBJPROP_TIME, 0);
   double   p2b = ObjectGetDouble(0, g2, OBJPROP_PRICE, 0);
   datetime t2c = (datetime)ObjectGetInteger(0, g2, OBJPROP_TIME, 1);
   double   p2c = ObjectGetDouble(0, g2, OBJPROP_PRICE, 1);

   DzAnchors prev;
   DzForkMetaLoad(id, prev);

   double eps = SymbolInfoDouble(_Symbol, SYMBOL_POINT) * 0.5;
   if(eps <= 0.0)
      eps = 1e-8;

   DzAnchors now;
   now.ok = true;
   now.ta = t1a;  now.pa = p1a;
   now.tc = t2c;  now.pc = p2c;

   if(!prev.ok)
     {
      now.tb = t1b;
      now.pb = p1b;
     }
   else
     {
      bool movedIn1 = (t1b != prev.tb || MathAbs(p1b - prev.pb) > eps);
      bool movedIn2 = (t2b != prev.tb || MathAbs(p2b - prev.pb) > eps);
      if(movedIn1)      { now.tb = t1b; now.pb = p1b; }
      else if(movedIn2) { now.tb = t2b; now.pb = p2b; }
      else              { now.tb = prev.tb; now.pb = prev.pb; }
     }

   DzForkDraw(id, now, DzForkColor(id));
  }

//+------------------------------------------------------------------+
//| Ein Klick, drei Anker: den naechstliegenden Schwung suchen.      |
//|                                                                  |
//| Im Fenster um die angeklickte Kerze werden Hoch und Tief         |
//| gesucht. Das aeltere der beiden ist der Start, das juengere die  |
//| Spitze. Der Ruecklauf ist das Gegenextrem danach.                |
//+------------------------------------------------------------------+
bool DzForkAuto(const datetime t, DzAnchors &a)
  {
   a.ok = false;

   int total = Bars(_Symbol, _Period);
   if(total < 10)
      return false;

   int bar = DzBarOf(t);
   int win = (g_fkAutoBars < 6 ? 6 : g_fkAutoBars);

   int start = bar + win / 2;                 // aeltere Kante des Fensters
   if(start > total - 1)
      start = total - 1;
   int stop = bar - win / 2;                  // juengere Kante
   if(stop < 0)
      stop = 0;

   int count = start - stop + 1;
   if(count < 4)
      return false;

   int hi = DzHighestIdx(stop, count);
   int lo = DzLowestIdx(stop, count);
   if(hi == lo)
      return false;

   int idxA, idxB;
   bool up;
   if(lo > hi)                                // Tief liegt weiter zurueck
     { idxA = lo; idxB = hi; up = true;  }
   else
     { idxA = hi; idxB = lo; up = false; }

   //--- Gegenextrem nach der Spitze ist der Ruecklauf
   int idxC = idxB;
   if(idxB > 0)
     {
      int after = idxB;                       // Kerzen 0 .. idxB-1
      idxC = (up ? DzLowestIdx(0, after) : DzHighestIdx(0, after));
     }

   a.ta = iTime(_Symbol, _Period, idxA);
   a.pa = (up ? iLow(_Symbol, _Period, idxA)  : iHigh(_Symbol, _Period, idxA));
   a.tb = iTime(_Symbol, _Period, idxB);
   a.pb = (up ? iHigh(_Symbol, _Period, idxB) : iLow(_Symbol, _Period, idxB));
   a.tc = iTime(_Symbol, _Period, idxC);
   a.pc = (up ? iLow(_Symbol, _Period, idxC)  : iHigh(_Symbol, _Period, idxC));

   if(a.ta <= 0 || a.tb <= 0 || a.tc <= 0)
      return false;
   if(MathAbs(a.pb - a.pa) <= 0.0)
      return false;

   a.ok = true;
   return true;
  }

//+------------------------------------------------------------------+
//| Wie viele Klicks braucht das scharfe Werkzeug noch               |
//+------------------------------------------------------------------+
int DzToolNeeds(void)
  {
   switch(g_dzTool)
     {
      case DZ_TOOL_RECT:
      case DZ_TOOL_ALARM:
      case DZ_TOOL_LINE:  return 2;
      case DZ_TOOL_FORK:  return (g_fkMode == DZ_FORK_1CLICK ? 1 : 3);
      default:            return 0;
     }
  }

//--- Text der Hinweiszeile zum aktuellen Stand
string DzToolHint(void)
  {
   if(g_dzTool == DZ_TOOL_NONE)
      return "";

   string what = "";
   switch(g_dzTool)
     {
      case DZ_TOOL_RECT:  what = "Rechteck";             break;
      case DZ_TOOL_ALARM: what = "Rechteck mit Alarm";   break;
      case DZ_TOOL_LINE:  what = "Trendlinie";           break;
      case DZ_TOOL_FORK:  what = "Dreizack";             break;
      default: break;
     }

   if(g_dzTool == DZ_TOOL_FORK && g_fkMode == DZ_FORK_3CLICK)
     {
      if(g_dzStep == 0) return what + ": Start des Impulses klicken  (Abbruch: Esc)";
      if(g_dzStep == 1) return what + ": Spitze klicken  (Abbruch: Esc)";
      return what + ": Ruecklauf klicken  (Abbruch: Esc)";
     }

   if(DzToolNeeds() == 1)
      return what + ": Stelle im Chart klicken  (Abbruch: Esc)";

   return what + (g_dzStep == 0 ? ": erste Ecke klicken  (Abbruch: Esc)"
                                : ": zweite Ecke klicken  (Abbruch: Esc)");
  }

//--- Werkzeug scharf schalten
void DzToolArm(const ENUM_DZ_TOOL tool, const color col, const string button)
  {
   g_dzTool      = tool;
   g_dzToolColor = col;
   g_dzStep      = 0;
   DzPanelArm(button);
   DzPanelHint(DzToolHint());
  }

//--- Werkzeug abwaehlen
void DzToolCancel(void)
  {
   g_dzTool      = DZ_TOOL_NONE;
   g_dzToolColor = clrNONE;
   g_dzStep      = 0;
   DzPanelArm("");
   DzPanelHint("");
  }

//+------------------------------------------------------------------+
//| Klick im Chart verarbeiten. Liefert true, wenn der Klick zu      |
//| einem Werkzeug gehoerte.                                         |
//+------------------------------------------------------------------+
bool DzToolClick(const datetime t, const double p)
  {
   if(g_dzTool == DZ_TOOL_NONE)
      return false;

   int need = DzToolNeeds();
   if(g_dzStep < 3)
     {
      g_dzT[g_dzStep] = t;
      g_dzP[g_dzStep] = p;
     }
   g_dzStep++;

   if(g_dzStep < need)
     {
      DzPanelHint(DzToolHint());
      ChartRedraw(0);
      return true;
     }

   //--- genug Punkte, Objekt bauen
   switch(g_dzTool)
     {
      case DZ_TOOL_RECT:
         DzMakeRect(g_dzT[0], g_dzP[0], g_dzT[1], g_dzP[1], g_dzToolColor, false);
         break;

      case DZ_TOOL_ALARM:
         DzMakeRect(g_dzT[0], g_dzP[0], g_dzT[1], g_dzP[1], g_dzToolColor, true);
         break;

      case DZ_TOOL_LINE:
         DzMakeLine(g_dzT[0], g_dzP[0], g_dzT[1], g_dzP[1], g_dzToolColor);
         break;

      case DZ_TOOL_FORK:
        {
         DzAnchors a;
         a.ok = false;
         if(g_fkMode == DZ_FORK_1CLICK)
           {
            if(!DzForkAuto(g_dzT[0], a))
               Print("Dreizack: im Suchfenster war kein brauchbarer Schwung. "
                     "Fenster vergroessern oder auf drei Klicks umstellen.");
           }
         else
           {
            a.ta = g_dzT[0]; a.pa = g_dzP[0];
            a.tb = g_dzT[1]; a.pb = g_dzP[1];
            a.tc = g_dzT[2]; a.pc = g_dzP[2];
            a.ok = (MathAbs(a.pb - a.pa) > 0.0);
            if(!a.ok)
               Print("Dreizack: Start und Spitze liegen auf demselben Kurs.");
           }
         if(a.ok)
            DzForkCreate(a, g_dzToolColor);
         break;
        }

      default:
         break;
     }

   DzToolCancel();
   ChartRedraw(0);
   return true;
  }

//+------------------------------------------------------------------+
//| Alle Zeichnungen dieses Indikators entfernen                     |
//+------------------------------------------------------------------+
int DzClearDrawings(void)
  {
   int n = 0;
   n += DzDeletePrefix(DZ_PRE_RECT);
   n += DzDeletePrefix(DZ_PRE_ALARM);
   n += DzDeletePrefix(DZ_PRE_LINE);
   n += DzDeletePrefix(DZ_PRE_FORK);
   return n;
  }

#endif // BAUBOX_DZ_TOOLS_MQH
//+------------------------------------------------------------------+
