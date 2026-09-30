//+------------------------------------------------------------------+
//|                                                       DzUtil.mqh |
//|               BauBox Dreizack - Farben, Objekte, Formatierung    |
//+------------------------------------------------------------------+
#ifndef BAUBOX_DZ_UTIL_MQH
#define BAUBOX_DZ_UTIL_MQH

#include "DzTypes.mqh"

//+------------------------------------------------------------------+
//| Farbkanaele. MQL5 legt Farben als 0x00BBGGRR ab.                 |
//+------------------------------------------------------------------+
int DzRed(const color c)   { return (int)(((uint)c)        & 0xFF); }
int DzGreen(const color c) { return (int)((((uint)c) >> 8)  & 0xFF); }
int DzBlue(const color c)  { return (int)((((uint)c) >> 16) & 0xFF); }

//--- Farbe aus Kanaelen, Werte werden begrenzt
color DzRGB(const int r, const int g, const int b)
  {
   int rr = (r < 0 ? 0 : (r > 255 ? 255 : r));
   int gg = (g < 0 ? 0 : (g > 255 ? 255 : g));
   int bb = (b < 0 ? 0 : (b > 255 ? 255 : b));
   return (color)((uint)((bb << 16) | (gg << 8) | rr));
  }

//--- lineare Mischung: k = 0 ergibt a, k = 1 ergibt b
color DzMix(const color a, const color b, const double k)
  {
   double t = (k < 0.0 ? 0.0 : (k > 1.0 ? 1.0 : k));
   return DzRGB((int)MathRound(DzRed(a)   + (DzRed(b)   - DzRed(a))   * t),
                (int)MathRound(DzGreen(a) + (DzGreen(b) - DzGreen(a)) * t),
                (int)MathRound(DzBlue(a)  + (DzBlue(b)  - DzBlue(a))  * t));
  }

//--- empfundene Helligkeit 0..255, entscheidet ueber schwarze oder weisse Schrift
int DzLuma(const color c)
  {
   return (int)((DzRed(c) * 299 + DzGreen(c) * 587 + DzBlue(c) * 114) / 1000);
  }

//--- lesbare Schriftfarbe auf einem farbigen Grund
color DzInk(const color bg)
  {
   return (DzLuma(bg) > 150 ? DzRGB(25, 25, 25) : DzRGB(245, 245, 245));
  }

//+------------------------------------------------------------------+
//| Loescht ein Objekt, falls vorhanden                              |
//+------------------------------------------------------------------+
void DzDelete(const string name)
  {
   if(ObjectFind(0, name) >= 0)
      ObjectDelete(0, name);
  }

//+------------------------------------------------------------------+
//| Loescht alle Objekte, deren Name mit dem Praefix beginnt.        |
//| Rueckwaerts, weil sich die Liste beim Loeschen verkuerzt.        |
//+------------------------------------------------------------------+
int DzDeletePrefix(const string prefix)
  {
   int n   = 0;
   int len = StringLen(prefix);
   for(int i = ObjectsTotal(0, -1, -1) - 1; i >= 0; i--)
     {
      string nm = ObjectName(0, i, -1, -1);
      if(StringSubstr(nm, 0, len) == prefix)
        {
         ObjectDelete(0, nm);
         n++;
        }
     }
   return n;
  }

//+------------------------------------------------------------------+
//| Zaehlt Objekte mit diesem Praefix                                |
//+------------------------------------------------------------------+
int DzCountPrefix(const string prefix)
  {
   int n   = 0;
   int len = StringLen(prefix);
   for(int i = ObjectsTotal(0, -1, -1) - 1; i >= 0; i--)
      if(StringSubstr(ObjectName(0, i, -1, -1), 0, len) == prefix)
         n++;
   return n;
  }

//+------------------------------------------------------------------+
//| Naechste freie laufende Nummer fuer ein Praefix.                 |
//|                                                                  |
//| Gesucht wird die groesste Zahl, die direkt hinter dem Praefix    |
//| steht - egal ob der Name dort endet (Rechteck) oder noch ein     |
//| Unterstrich mit einem Teilnamen folgt (Dreizack).                |
//+------------------------------------------------------------------+
long DzNextId(const string prefix)
  {
   long best = 0;
   int  len  = StringLen(prefix);
   for(int i = ObjectsTotal(0, -1, -1) - 1; i >= 0; i--)
     {
      string nm = ObjectName(0, i, -1, -1);
      if(StringSubstr(nm, 0, len) != prefix)
         continue;
      string rest = StringSubstr(nm, len);
      int    cut  = StringFind(rest, "_");
      if(cut >= 0)
         rest = StringSubstr(rest, 0, cut);
      long v = StringToInteger(rest);
      if(v > best)
         best = v;
     }
   return best + 1;
  }

//+------------------------------------------------------------------+
//| Name eines Dreizackteils                                         |
//+------------------------------------------------------------------+
string DzForkPart(const long id, const string part)
  {
   return DZ_PRE_FORK + IntegerToString(id) + "_" + part;
  }

//+------------------------------------------------------------------+
//| Holt aus einem Dreizacknamen die laufende Nummer, sonst -1       |
//+------------------------------------------------------------------+
long DzForkIdOf(const string name)
  {
   int len = StringLen(DZ_PRE_FORK);
   if(StringSubstr(name, 0, len) != DZ_PRE_FORK)
      return -1;
   string rest = StringSubstr(name, len);
   int    cut  = StringFind(rest, "_");
   if(cut <= 0)
      return -1;
   return StringToInteger(StringSubstr(rest, 0, cut));
  }

//+------------------------------------------------------------------+
//| Holt aus einem Dreizacknamen den Teilnamen, sonst ""             |
//|                                                                  |
//| "DZ_T_7_G1" ergibt "G1". Damit laesst sich unterscheiden, ob ein |
//| geloeschtes Objekt ein Schenkel war - nur die kann der Anwender  |
//| ueberhaupt auswaehlen - oder ein Beiwerk, das der Indikator      |
//| selbst weggeraeumt hat.                                          |
//+------------------------------------------------------------------+
string DzForkPartOf(const string name)
  {
   int len = StringLen(DZ_PRE_FORK);
   if(StringSubstr(name, 0, len) != DZ_PRE_FORK)
      return "";
   string rest = StringSubstr(name, len);
   int    cut  = StringFind(rest, "_");
   if(cut < 0)
      return "";
   return StringSubstr(rest, cut + 1);
  }

//+------------------------------------------------------------------+
//| Taste anlegen oder auffrischen                                   |
//+------------------------------------------------------------------+
void DzButton(const string name, const int corner, const int x, const int y,
              const int w, const int h, const color bg, const color border,
              const string text, const string font, const int fontsize,
              const color ink, const string tip)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER,       corner);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE,    x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE,    y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE,        w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE,        h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR,      bg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, border);
   ObjectSetInteger(0, name, OBJPROP_COLOR,        ink);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE,     fontsize);
   ObjectSetInteger(0, name, OBJPROP_BACK,         false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE,   false);
   ObjectSetInteger(0, name, OBJPROP_SELECTED,     false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,       true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER,       10);
   //--- Eine Taste in MetaTrader rastet beim Klick ein. Beim Aufbau
   //--- der Leiste ist nichts scharf, also gehoert sie herausgerastet;
   //--- sonst stuende nach einem Zeitrahmenwechsel noch die Taste von
   //--- vorhin gedrueckt da, ohne dass ein Werkzeug wartet.
   ObjectSetInteger(0, name, OBJPROP_STATE,        false);
   ObjectSetString(0,  name, OBJPROP_FONT,         font);
   ObjectSetString(0,  name, OBJPROP_TEXT,         text);
   ObjectSetString(0,  name, OBJPROP_TOOLTIP,      tip == "" ? "\n" : tip);
  }

//+------------------------------------------------------------------+
//| Textfeld am Pixelraster anlegen oder auffrischen                 |
//+------------------------------------------------------------------+
void DzLabel(const string name, const int corner, const int x, const int y,
             const string text, const color ink, const string font,
             const int fontsize, const ENUM_ANCHOR_POINT anchor)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER,     corner);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE,  x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE,  y);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR,     anchor);
   ObjectSetInteger(0, name, OBJPROP_COLOR,      ink);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE,   fontsize);
   ObjectSetInteger(0, name, OBJPROP_BACK,       false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTED,   false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,     true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER,     20);
   ObjectSetString(0,  name, OBJPROP_FONT,       font);
   ObjectSetString(0,  name, OBJPROP_TEXT,       text);
  }

//+------------------------------------------------------------------+
//| Flaeche am Pixelraster anlegen oder auffrischen                  |
//+------------------------------------------------------------------+
void DzPane(const string name, const int corner, const int x, const int y,
            const int w, const int h, const color bg, const color border)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER,      corner);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE,   x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE,   y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE,       w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE,       h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR,     bg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, name, OBJPROP_COLOR,       border);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,       1);
   ObjectSetInteger(0, name, OBJPROP_BACK,        false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE,  false);
   ObjectSetInteger(0, name, OBJPROP_SELECTED,    false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,      true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER,      0);
  }

//+------------------------------------------------------------------+
//| Sekunden als Uhrzeit. Unter einer Stunde ohne Stundenfeld.       |
//+------------------------------------------------------------------+
string DzClock(const long secs)
  {
   long s = (secs < 0 ? 0 : secs);
   long h = s / 3600;
   long m = (s % 3600) / 60;
   long r = s % 60;
   if(h > 0)
      return StringFormat("%d:%02d:%02d", (int)h, (int)m, (int)r);
   return StringFormat("%02d:%02d", (int)m, (int)r);
  }

//+------------------------------------------------------------------+
//| Minuten seit Mitternacht als "HH:MM"                             |
//+------------------------------------------------------------------+
string DzHhMm(const int minutes)
  {
   int m = ((minutes % 1440) + 1440) % 1440;
   return StringFormat("%02d:%02d", m / 60, m % 60);
  }

//+------------------------------------------------------------------+
//| Kuerzel des Chartzeitrahmens, z. B. "M5"                         |
//+------------------------------------------------------------------+
string DzPeriodName(const ENUM_TIMEFRAMES tf)
  {
   string s = EnumToString(tf);          // "PERIOD_M5"
   int    p = StringFind(s, "_");
   return (p >= 0 ? StringSubstr(s, p + 1) : s);
  }

//+------------------------------------------------------------------+
//| Preisabstand in Punkten                                          |
//+------------------------------------------------------------------+
double DzPoints(const double diff)
  {
   double pt = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(pt <= 0.0)
      return 0.0;
   return MathAbs(diff) / pt;
  }

//+------------------------------------------------------------------+
//| Ganze Zahl mit Tausenderpunkten, z. B. 3189 -> "3.189"           |
//+------------------------------------------------------------------+
string DzGroup(const double v)
  {
   long   n   = (long)MathRound(MathAbs(v));
   string s   = IntegerToString(n);
   int    len = StringLen(s);
   string out = "";
   for(int i = 0; i < len; i++)
     {
      if(i > 0 && ((len - i) % 3) == 0)
         out += ".";
      out += StringSubstr(s, i, 1);
     }
   return (v < 0.0 ? "-" : "") + out;
  }

#endif // BAUBOX_DZ_UTIL_MQH
//+------------------------------------------------------------------+
