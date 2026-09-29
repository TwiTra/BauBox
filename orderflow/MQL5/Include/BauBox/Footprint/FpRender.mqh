//+------------------------------------------------------------------+
//|                                                     FpRender.mqh |
//|      BauBox Footprint - zeichnet die Cluster auf eine Leinwand   |
//+------------------------------------------------------------------+
#ifndef BAUBOX_FP_RENDER_MQH
#define BAUBOX_FP_RENDER_MQH

#include <Canvas\Canvas.mqh>
#include "FpEngine.mqh"

//+------------------------------------------------------------------+
//| Alles, was das Aussehen bestimmt                                 |
//+------------------------------------------------------------------+
struct FpStyle
  {
   ENUM_FP_MODE      mode;
   ENUM_FP_INTENSITY intensity;
   color             bull;        // Kaufuebergewicht
   color             bear;        // Verkaufsuebergewicht
   color             neutral;     // ausgeglichen
   color             textLight;   // Schrift auf dunklem Grund
   color             textDark;    // Schrift auf hellem Grund
   color             imb;         // Zahl mit Ungleichgewicht
   color             frame;       // Rahmen um Serien
   color             poc;         // Rahmen um den Point of Control
   color             va;          // Markierung der Value Area
   color             unfinished;  // unvollendete Auktion
   color             candleUp;
   color             candleDn;
   color             info;        // Schrift der Kopfzeile
   int               alpha;       // Deckkraft der Zellen 0..255
   bool              showCandle;
   bool              showHeadTop;
   bool              showHeadBottom;
   bool              showPoc;
   bool              showVa;
   bool              showUnfinished;
   bool              showInfo;
   string            font;
   int               fontMax;     // groesste Schriftgroesse in Punkt
   int               fontMin;     // kleinste Schriftgroesse in Punkt
   int               gapX;        // Luft zwischen zwei Spalten
   int               minCellH;    // ab dieser Zellhoehe wird Text gezeichnet
  };

//+------------------------------------------------------------------+
//| Die Leinwand ueber dem Chart                                     |
//+------------------------------------------------------------------+
class CFpRender
  {
private:
   CCanvas           m_c;
   string            m_obj;
   int               m_w, m_h;
   double            m_pmax, m_ppp;
   int               m_cw, m_chh;      // Breite und Hoehe eines Zeichens
   int               m_hcw, m_hch;     // dasselbe fuer die Kopfzeilen
   //--- Zwischenspeicher fuer den Sichtbereich
   CFpBar           *m_vb[];
   int               m_vx[];
   int               m_vn;

   int               PY(const double p) { return (int)MathRound((m_pmax - p) * m_ppp); }
   int               PickFont(FpStyle &st, const int maxH, const int maxW, const string sample);
   color             CellColor(CFpBar *b, const int i, FpStyle &st);
   void              DrawCells(CFpBar *b, FpStyle &st, CFpEngine &eng,
                               const int xc, const int bw, const int cellH, const bool withText);
   void              DrawHead(CFpBar *b, FpStyle &st, CFpEngine &eng, const int xc, const int bw);
   void              DrawInfo(FpStyle &st, CFpEngine &eng, const string sym);
   void              Box(const int x1, const int y1, const int x2, const int y2, const uint clr);

public:
                     CFpRender(void);
   bool              Create(const string name);
   void              Destroy(void);
   bool              Sync(void);
   void              Draw(CFpEngine &eng, FpStyle &st, const string sym,
                          const ENUM_TIMEFRAMES tf, const int shiftFrom, const int shiftTo);
  };

//+------------------------------------------------------------------+
CFpRender::CFpRender(void)
  {
   m_obj  = "";
   m_w    = 0;
   m_h    = 0;
   m_pmax = 0.0;
   m_ppp  = 0.0;
   m_cw   = 0;
   m_chh  = 0;
   m_hcw  = 0;
   m_hch  = 0;
   m_vn   = 0;
  }

//+------------------------------------------------------------------+
//| Leinwand anlegen, genau so gross wie das Hauptfenster            |
//+------------------------------------------------------------------+
bool CFpRender::Create(const string name)
  {
   m_obj = name;
   m_w = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   m_h = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS, 0);
   if(m_w < 10)
      m_w = 10;
   if(m_h < 10)
      m_h = 10;

   if(!m_c.CreateBitmapLabel(m_obj, 0, 0, m_w, m_h, COLOR_FORMAT_ARGB_NORMALIZE))
      return false;

   ObjectSetInteger(0, m_obj, OBJPROP_CORNER,     CORNER_LEFT_UPPER);
   ObjectSetInteger(0, m_obj, OBJPROP_XDISTANCE,  0);
   ObjectSetInteger(0, m_obj, OBJPROP_YDISTANCE,  0);
   ObjectSetInteger(0, m_obj, OBJPROP_BACK,       false);
   ObjectSetInteger(0, m_obj, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, m_obj, OBJPROP_SELECTED,   false);
   ObjectSetInteger(0, m_obj, OBJPROP_HIDDEN,     true);
   ObjectSetInteger(0, m_obj, OBJPROP_ZORDER,     0);
   return true;
  }

//+------------------------------------------------------------------+
void CFpRender::Destroy(void)
  {
   m_c.Destroy();
   if(m_obj != "")
      ObjectDelete(0, m_obj);
   m_obj = "";
  }

//+------------------------------------------------------------------+
//| Groesse an das Chartfenster angleichen                           |
//+------------------------------------------------------------------+
bool CFpRender::Sync(void)
  {
   int w = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int h = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS, 0);
   if(w < 10)
      w = 10;
   if(h < 10)
      h = 10;
   if(w == m_w && h == m_h)
      return true;
   m_w = w;
   m_h = h;
   if(!m_c.Resize(w, h))
      return false;
   ObjectSetInteger(0, m_obj, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, m_obj, OBJPROP_YSIZE, h);
   return true;
  }

//+------------------------------------------------------------------+
//| Rechteck-Umriss, auf die Leinwand begrenzt                       |
//+------------------------------------------------------------------+
void CFpRender::Box(const int x1, const int y1, const int x2, const int y2, const uint clr)
  {
   int a = (x1 < 0 ? 0 : x1);
   int b = (y1 < 0 ? 0 : y1);
   int c = (x2 > m_w - 1 ? m_w - 1 : x2);
   int d = (y2 > m_h - 1 ? m_h - 1 : y2);
   if(a >= c || b >= d)
      return;
   m_c.Rectangle(a, b, c, d, clr);
  }

//+------------------------------------------------------------------+
//| Groesste Schrift suchen, die in Hoehe und Breite passt.          |
//| CCanvas nimmt die Groesse mal -10 als Pixelhoehe entgegen.        |
//| Rueckgabe: Pixelhoehe oder -1, wenn nichts passt.                 |
//+------------------------------------------------------------------+
int CFpRender::PickFont(FpStyle &st, const int maxH, const int maxW, const string sample)
  {
   for(int px = st.fontMax; px >= st.fontMin; px--)
     {
      m_c.FontSet(st.font, -px * 10, 0);
      int th = m_c.TextHeight("8");
      int tw = m_c.TextWidth(sample);
      if(th <= maxH && tw <= maxW)
         return px;
     }
   return -1;
  }

//+------------------------------------------------------------------+
//| Farbe einer Zelle                                                |
//+------------------------------------------------------------------+
color CFpRender::CellColor(CFpBar *b, const int i, FpStyle &st)
  {
   double d = b.CellDelta(i);
   double k = 0.0;
   if(st.intensity == FP_INT_DELTA)
      k = (b.maxAbsDelta > 0.0 ? MathAbs(d) / b.maxAbsDelta : 0.0);
   else
      k = (b.maxCellVol > 0.0 ? b.CellVol(i) / b.maxCellVol : 0.0);
   k = MathPow(k, 0.65);            // schwache Werte etwas anheben
   color base = (d > 0.0 ? st.bull : (d < 0.0 ? st.bear : st.neutral));
   return FpMix(st.neutral, base, k);
  }

//+------------------------------------------------------------------+
//| Zellen einer Kerze                                               |
//+------------------------------------------------------------------+
void CFpRender::DrawCells(CFpBar *b, FpStyle &st, CFpEngine &eng,
                          const int xc, const int bw, const int cellH, const bool withText)
  {
   int n = b.Count();
   if(n <= 0)
      return;

   int half = bw / 2;
   int xl   = xc - half + st.gapX;
   int xr   = xc + half - st.gapX;
   if(xr - xl < 3)
     {
      xl = xc - 1;
      xr = xc + 1;
     }
   if(xr < 0 || xl > m_w)
      return;

   int candleW = ((st.showCandle && (xr - xl) >= 16) ? 6 : 0);
   int cellL   = xl + candleW;
   int cellW   = xr - cellL;
   if(cellW < 2)
      return;

   double ls = eng.LevelSize();

   //--- Kerzenkoerper und Docht links neben der Spalte
   if(candleW > 0 && b.high > 0.0)
     {
      color cc  = (b.close >= b.open ? st.candleUp : st.candleDn);
      uint  acc = ColorToARGB(cc, 255);
      int   yo  = PY(b.open);
      int   ycl = PY(b.close);
      int   yt  = (yo < ycl ? yo : ycl);
      int   yb  = (yo < ycl ? ycl : yo);
      if(yb - yt < 1)
         yb = yt + 1;
      m_c.FillRectangle(xl, yt, xl + candleW - 3, yb, acc);
      int xm = xl + (candleW - 3) / 2;
      m_c.FillRectangle(xm, PY(b.high), xm, PY(b.low), acc);
     }

   //--- Profilmodus: nur Balken, keine Zahlen
   bool profile = (st.mode == FP_MODE_PROFILE);

   for(int i = 0; i < n; i++)
     {
      double pLow = eng.LevelLow(b.LevelAt(i));
      int    yb   = PY(pLow);
      int    yt   = PY(pLow + ls);
      if(yb < 0 || yt > m_h)
         continue;
      if(yb - yt < 1)
         yb = yt + 1;

      color bg = CellColor(b, i, st);

      if(profile)
        {
         double k = (b.maxCellVol > 0.0 ? b.CellVol(i) / b.maxCellVol : 0.0);
         int    wpx = (int)MathRound(cellW * k);
         if(wpx < 1)
            wpx = 1;
         m_c.FillRectangle(cellL, yt, cellL + wpx, yb - 1, ColorToARGB(bg, (uchar)st.alpha));
        }
      else
         m_c.FillRectangle(cellL, yt, xr, yb - 1, ColorToARGB(bg, (uchar)st.alpha));

      //--- Value Area als schmaler Streifen am rechten Rand
      if(st.showVa && (b.cells[i].flags & FP_F_VA) != 0 && !profile)
         m_c.FillRectangle(xr - 1, yt, xr, yb - 1, ColorToARGB(st.va, 255));

      //--- Text
      if(withText && !profile)
        {
         color tc = (FpLuma(bg) > 145 ? st.textDark : st.textLight);
         int   ty = (yt + yb) / 2;

         if(st.mode == FP_MODE_BIDASK)
           {
            string sb = FpCellNum(b.cells[i].bid);
            string sa = FpCellNum(b.cells[i].ask);
            int    lb = StringLen(sb);
            int    la = StringLen(sa);
            int    tw = (lb + 1 + la) * m_cw;
            int    tx = cellL + (cellW - tw) / 2;
            color  cb = ((b.cells[i].flags & FP_F_BID_IMB) != 0 ? st.imb : tc);
            color  ca = ((b.cells[i].flags & FP_F_ASK_IMB) != 0 ? st.imb : tc);
            m_c.TextOut(tx,                    ty, sb,  ColorToARGB(cb, 255), TA_LEFT | TA_VCENTER);
            m_c.TextOut(tx + lb * m_cw,        ty, "x", ColorToARGB(tc, 255), TA_LEFT | TA_VCENTER);
            m_c.TextOut(tx + (lb + 1) * m_cw,  ty, sa,  ColorToARGB(ca, 255), TA_LEFT | TA_VCENTER);
           }
         else
           {
            string s = (st.mode == FP_MODE_DELTA ? FpSigned(b.CellDelta(i)) : FpCellNum(b.CellVol(i)));
            int    tx = cellL + (cellW - StringLen(s) * m_cw) / 2;
            m_c.TextOut(tx, ty, s, ColorToARGB(tc, 255), TA_LEFT | TA_VCENTER);
           }
        }

      //--- Rahmen um Serien gestapelter Ungleichgewichte
      if((b.cells[i].flags & FP_F_STACK) != 0)
        {
         Box(cellL, yt, xr, yb - 1, ColorToARGB(st.frame, 255));
         Box(cellL + 1, yt + 1, xr - 1, yb - 2, ColorToARGB(st.frame, 255));
        }

      //--- Point of Control
      if(st.showPoc && i == b.pocIdx)
         Box(cellL, yt, xr, yb - 1, ColorToARGB(st.poc, 255));
     }

   //--- unvollendete Auktion an den Extremen
   if(st.showUnfinished && n > 0)
     {
      uint uc = ColorToARGB(st.unfinished, 255);
      if(b.unfHigh)
        {
         int y = PY(eng.LevelLow(b.LevelAt(n - 1)) + ls);
         m_c.FillRectangle(cellL, y, xr, y + 1, uc);
        }
      if(b.unfLow)
        {
         int y = PY(eng.LevelLow(b.LevelAt(0)));
         m_c.FillRectangle(cellL, y - 1, xr, y, uc);
        }
     }
  }

//+------------------------------------------------------------------+
//| Delta und Volumen ueber bzw. unter der Spalte                    |
//+------------------------------------------------------------------+
void CFpRender::DrawHead(CFpBar *b, FpStyle &st, CFpEngine &eng, const int xc, const int bw)
  {
   int n = b.Count();
   if(n <= 0 || m_hcw <= 0)
      return;

   double ls   = eng.LevelSize();
   int    yTop = PY(eng.LevelLow(b.LevelAt(n - 1)) + ls);
   int    yBot = PY(eng.LevelLow(b.LevelAt(0)));

   string sd = FpSymDelta() + " " + (b.delta > 0.0 ? "+" : "") + FpGroup(b.delta);
   string sv = FpSymSigma() + " " + FpGroup(b.volume);
   if(b.approx)
      sv = FpSymApprox() + " " + sv;
   color  cd = (b.delta > 0.0 ? st.bull : (b.delta < 0.0 ? st.bear : st.info));

   int line = m_hch + 2;

   if(st.showHeadTop)
     {
      int y = yTop - 4 - line;
      m_c.TextOut(xc - (StringLen(sd) * m_hcw) / 2, y,        sd, ColorToARGB(cd, 255), TA_LEFT | TA_BOTTOM);
      m_c.TextOut(xc - (StringLen(sv) * m_hcw) / 2, y + line, sv, ColorToARGB(st.info, 255), TA_LEFT | TA_BOTTOM);
     }
   if(st.showHeadBottom)
     {
      int y = yBot + 4;
      m_c.TextOut(xc - (StringLen(sv) * m_hcw) / 2, y,        sv, ColorToARGB(st.info, 255), TA_LEFT | TA_TOP);
      m_c.TextOut(xc - (StringLen(sd) * m_hcw) / 2, y + line, sd, ColorToARGB(cd, 255), TA_LEFT | TA_TOP);
     }
  }

//+------------------------------------------------------------------+
//| Kopfzeile oben links                                             |
//+------------------------------------------------------------------+
void CFpRender::DrawInfo(FpStyle &st, CFpEngine &eng, const string sym)
  {
   m_c.FontSet(st.font, -100, 0);
   int  lh = m_c.TextHeight("8") + 3;

   string tfName = EnumToString((ENUM_TIMEFRAMES)Period());
   if(StringSubstr(tfName, 0, 7) == "PERIOD_")
      tfName = StringSubstr(tfName, 7);
   string l1 = sym + "  " + tfName;
   string l2 = "Raster " + IntegerToString(eng.TicksPerLevel()) + " Ticks = "
               + DoubleToString(eng.LevelSize(), (int)SymbolInfoInteger(sym, SYMBOL_DIGITS));
   string l3 = "Quelle: " + eng.SourceText();
   if(eng.Pending() > 0)
      l3 += "  (" + IntegerToString(eng.Pending()) + " laden...)";

   int w = m_c.TextWidth(l1);
   int w2 = m_c.TextWidth(l2);
   int w3 = m_c.TextWidth(l3);
   if(w2 > w)
      w = w2;
   if(w3 > w)
      w = w3;

   m_c.FillRectangle(4, 4, 12 + w, 10 + 3 * lh, ColorToARGB(clrBlack, 110));
   m_c.TextOut(8, 7,          l1, ColorToARGB(st.info, 255), TA_LEFT | TA_TOP);
   m_c.TextOut(8, 7 + lh,     l2, ColorToARGB(st.info, 255), TA_LEFT | TA_TOP);
   m_c.TextOut(8, 7 + 2 * lh, l3, ColorToARGB(st.info, 255), TA_LEFT | TA_TOP);
  }

//+------------------------------------------------------------------+
//| Kompletter Neuaufbau des Bildes                                  |
//+------------------------------------------------------------------+
void CFpRender::Draw(CFpEngine &eng, FpStyle &st, const string sym,
                     const ENUM_TIMEFRAMES tf, const int shiftFrom, const int shiftTo)
  {
   m_c.Erase(0);

   double pmin = ChartGetDouble(0, CHART_PRICE_MIN, 0);
   double pmax = ChartGetDouble(0, CHART_PRICE_MAX, 0);
   int    h0   = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS, 0);
   if(pmax <= pmin || h0 <= 0)
     {
      m_c.Update();
      return;
     }
   m_pmax = pmax;
   m_ppp  = (double)h0 / (pmax - pmin);

   double ls    = eng.LevelSize();
   int    cellH = (int)MathRound(ls * m_ppp);
   if(cellH < 1)
      cellH = 1;

   //--- Spaltenbreite aus zwei benachbarten Kerzen
   int bw = 0;
   int xa = 0, xb = 0, yy = 0;
   datetime ta = iTime(sym, tf, shiftTo);
   datetime tb = iTime(sym, tf, shiftTo + 1);
   if(ta > 0 && tb > 0 &&
      ChartTimePriceToXY(0, 0, ta, pmax, xa, yy) &&
      ChartTimePriceToXY(0, 0, tb, pmax, xb, yy))
      bw = xa - xb;
   if(bw <= 0)
     {
      int wb = (int)ChartGetInteger(0, CHART_WIDTH_IN_BARS);
      bw = (wb > 0 ? m_w / wb : 8);
     }
   if(bw < 2)
      bw = 2;

   //--- Ankert ChartTimePriceToXY in der Mitte der Spalte oder an einem Rand?
   //    Statt das anzunehmen, wird es einmal je Bild ausgemessen.
   int xoff = 0;
   if(bw >= 6)
     {
      int      xm = 0, ym = 0, sw = 0;
      datetime tl = 0, tr = 0;
      double   pp = 0.0;
      datetime tref = iTime(sym, tf, shiftTo + 1);
      if(tref > 0 && ChartTimePriceToXY(0, 0, tref, pmax, xm, ym))
        {
         int probe = bw / 2 - 2;
         if(probe < 1)
            probe = 1;
         int yp = m_h / 2;
         if(ChartXYToTimePrice(0, xm - probe, yp, sw, tl, pp) &&
            ChartXYToTimePrice(0, xm + probe, yp, sw, tr, pp))
           {
            if(tl != tref && tr == tref)
               xoff = bw / 2;          // x zeigt auf den linken Rand
            else
               if(tl == tref && tr != tref)
                  xoff = -bw / 2;      // x zeigt auf den rechten Rand
           }
        }
     }

   //--- Sichtbereich einsammeln
   int cap = shiftFrom - shiftTo + 1;
   if(cap < 1)
      cap = 1;
   ArrayResize(m_vb, cap);
   ArrayResize(m_vx, cap);
   m_vn = 0;

   double gcell = 0.0;
   for(int s = shiftTo; s <= shiftFrom; s++)
     {
      datetime t = iTime(sym, tf, s);
      if(t == 0)
         continue;
      CFpBar *b = eng.Find(t);
      if(b == NULL || !b.built || b.empty)
         continue;
      int x = 0, y = 0;
      if(!ChartTimePriceToXY(0, 0, t, pmax, x, y))
         continue;
      if(x < -bw || x > m_w + bw)
         continue;
      m_vb[m_vn] = b;
      m_vx[m_vn] = x + xoff;
      m_vn++;
      if(b.maxCellVol > gcell)
         gcell = b.maxCellVol;
     }

   if(m_vn == 0)
     {
      if(st.showInfo)
         DrawInfo(st, eng, sym);
      m_c.Update();
      return;
     }

   //--- Schrift fuer die Zellen
   int    half    = bw / 2;
   int    cellW   = (2 * half - 2 * st.gapX) - ((st.showCandle && (2 * half - 2 * st.gapX) >= 16) ? 6 : 0);
   string sample  = "";
   int    digits  = FpCellNumLen(gcell);
   if(digits < 1)
      digits = 1;
   for(int i = 0; i < digits; i++)
      sample += "8";
   if(st.mode == FP_MODE_BIDASK)
     {
      sample += "x";
      for(int i = 0; i < digits; i++)
         sample += "8";
     }
   else
      if(st.mode == FP_MODE_DELTA)
         sample = "-" + sample;

   bool withText = false;
   if(st.mode != FP_MODE_PROFILE && cellH >= st.minCellH && cellW > 6)
     {
      int pt = PickFont(st, cellH - 1, cellW - 2, sample);
      if(pt > 0)
        {
         m_cw     = m_c.TextWidth("8");
         m_chh    = m_c.TextHeight("8");
         withText = (m_cw > 0);
        }
     }

   //--- erste Runde: Zellen
   for(int i = 0; i < m_vn; i++)
      DrawCells(m_vb[i], st, eng, m_vx[i], bw, cellH, withText);

   //--- zweite Runde: Kopfzahlen
   if(st.showHeadTop || st.showHeadBottom)
     {
      int pt = PickFont(st, 40, bw - 2, FpSymSigma() + " 888.888");
      if(pt > 0)
        {
         m_hcw = m_c.TextWidth("8");
         m_hch = m_c.TextHeight("8");
         for(int i = 0; i < m_vn; i++)
            DrawHead(m_vb[i], st, eng, m_vx[i], bw);
        }
      else
         m_hcw = 0;
     }

   if(st.showInfo)
      DrawInfo(st, eng, sym);

   m_c.Update();
  }

#endif
