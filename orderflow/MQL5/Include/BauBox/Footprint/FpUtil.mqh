//+------------------------------------------------------------------+
//|                                                       FpUtil.mqh |
//|                    BauBox Footprint - kleine Hilfsfunktionen     |
//+------------------------------------------------------------------+
#ifndef BAUBOX_FP_UTIL_MQH
#define BAUBOX_FP_UTIL_MQH

//+------------------------------------------------------------------+
//| Farbkanaele. MQL5 legt Farben als 0x00BBGGRR ab.                 |
//+------------------------------------------------------------------+
int FpRed(const color c)   { return (int)(((uint)c)       & 0xFF); }
int FpGreen(const color c) { return (int)((((uint)c) >> 8)  & 0xFF); }
int FpBlue(const color c)  { return (int)((((uint)c) >> 16) & 0xFF); }

//--- Farbe aus Kanaelen, Werte werden begrenzt
color FpRGB(const int r, const int g, const int b)
  {
   int rr = (r < 0 ? 0 : (r > 255 ? 255 : r));
   int gg = (g < 0 ? 0 : (g > 255 ? 255 : g));
   int bb = (b < 0 ? 0 : (b > 255 ? 255 : b));
   return (color)((uint)((bb << 16) | (gg << 8) | rr));
  }

//--- lineare Mischung: k = 0 ergibt a, k = 1 ergibt b
color FpMix(const color a, const color b, const double k)
  {
   double t = (k < 0.0 ? 0.0 : (k > 1.0 ? 1.0 : k));
   return FpRGB((int)MathRound(FpRed(a)   + (FpRed(b)   - FpRed(a))   * t),
                (int)MathRound(FpGreen(a) + (FpGreen(b) - FpGreen(a)) * t),
                (int)MathRound(FpBlue(a)  + (FpBlue(b)  - FpBlue(a))  * t));
  }

//--- empfundene Helligkeit 0..255, entscheidet ueber schwarze oder weisse Schrift
int FpLuma(const color c)
  {
   return (int)((FpRed(c) * 299 + FpGreen(c) * 587 + FpBlue(c) * 114) / 1000);
  }

//--- Sonderzeichen ueber den Codepunkt, damit die Datei reines ASCII bleiben kann
string FpSymDelta(void) { return ShortToString(0x0394); }   // grosses Delta
string FpSymSigma(void) { return ShortToString(0x03A3); }   // grosses Sigma
string FpSymApprox(void){ return ShortToString(0x2248); }   // ungefaehr-Zeichen

//+------------------------------------------------------------------+
//| Ganze Zahl mit Tausenderpunkten, z. B. 3189 -> "3.189"           |
//+------------------------------------------------------------------+
string FpGroup(const double v)
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

//+------------------------------------------------------------------+
//| Zellenzahl. Ab fuenf Stellen wird gekuerzt, sonst passt sie nicht |
//+------------------------------------------------------------------+
string FpCellNum(const double v)
  {
   double a = MathAbs(v);
   if(a < 9999.5)
      return IntegerToString((long)MathRound(v));
   if(a < 999500.0)
     {
      double k = v / 1000.0;
      return DoubleToString(k, (MathAbs(k) < 99.95 ? 1 : 0)) + "k";
     }
   return DoubleToString(v / 1000000.0, 1) + "M";
  }

//--- Stellenzahl, die FpCellNum fuer diesen Wert hoechstens braucht
int FpCellNumLen(const double v)
  {
   return StringLen(FpCellNum(v));
  }

//--- Vorzeichenbehaftete Zahl mit fuehrendem + oder -
string FpSigned(const double v)
  {
   string s = FpCellNum(MathAbs(v));
   if(v > 0.0)  return "+" + s;
   if(v < 0.0)  return "-" + s;
   return "0";
  }

#endif
