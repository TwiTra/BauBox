//+------------------------------------------------------------------+
//|                                                    Footprint.mq5 |
//|                                                           BauBox |
//|                                                                  |
//| Footprint- bzw. Orderflow-Chart fuer MetaTrader 5.               |
//| Jede Kerze wird in Preisebenen zerlegt. Je Ebene steht, wie viel |
//| am Bid (aggressive Verkaeufe) und wie viel am Ask (aggressive    |
//| Kaeufe) gehandelt wurde. Dazu Delta, Volumen, Point of Control,  |
//| Value Area und diagonale Ungleichgewichte.                       |
//+------------------------------------------------------------------+
#property copyright "BauBox"
#property link      "https://github.com/TwiTra/BauBox"
#property version   "1.00"
#property description "Footprint / Orderflow: Bid x Ask je Preisebene, Delta, Ungleichgewichte"
#property indicator_chart_window
#property indicator_buffers 5
#property indicator_plots   5

#property indicator_type1   DRAW_NONE
#property indicator_label1  "Delta"
#property indicator_type2   DRAW_NONE
#property indicator_label2  "Delta kumuliert"
#property indicator_type3   DRAW_NONE
#property indicator_label3  "POC"
#property indicator_type4   DRAW_NONE
#property indicator_label4  "Volumen"
#property indicator_type5   DRAW_NONE
#property indicator_label5  "Serien-Signal"

#include <BauBox\Footprint\FpRender.mqh>

//--- Preisraster -----------------------------------------------------
input group                 "Preisraster"
input int                   InpTicksPerLevel  = 0;              // Ticks je Preisebene (0 = automatisch)
input int                   InpAutoLevels     = 16;             // Automatik: angepeilte Ebenen je Kerze

//--- Datenquelle -----------------------------------------------------
input group                 "Datenquelle"
input ENUM_FP_SOURCE        InpSource         = FP_SRC_AUTO;    // Quelle
input ENUM_FP_QPRICE        InpQuotePrice     = FP_QP_BID;      // Bei Bid/Ask-Ticks: Kurs der Ebene
input bool                  InpAllowM1        = true;           // Naeherung aus M1, wenn Ticks fehlen
input int                   InpMaxBars        = 150;            // Kerzen im Speicher
input int                   InpBudget         = 6;              // Kerzen je Arbeitsschritt

//--- Anzeige ---------------------------------------------------------
input group                 "Anzeige"
input ENUM_FP_MODE          InpMode           = FP_MODE_BIDASK; // Darstellung
input ENUM_FP_INTENSITY     InpIntensity      = FP_INT_DELTA;   // Farbstaerke richtet sich nach
input string                InpFont           = "Consolas";     // Schrift (gleiche Zeichenbreite empfohlen)
input int                   InpFontMax        = 13;             // groesste Schrifthoehe in Pixeln
input int                   InpFontMin        = 7;              // kleinste Schrifthoehe in Pixeln
input int                   InpAlpha          = 235;            // Deckkraft der Zellen (0..255)
input int                   InpGapX           = 2;              // Luft zwischen zwei Spalten
input int                   InpMinCellHeight  = 9;              // ab dieser Zellhoehe erscheinen Zahlen
input bool                  InpShowCandle     = true;           // eigene Kerze links der Spalte
input bool                  InpHeadTop        = true;           // Delta und Volumen ueber der Spalte
input bool                  InpHeadBottom     = false;          // Delta und Volumen unter der Spalte
input bool                  InpShowPoc        = true;           // Point of Control umranden
input bool                  InpShowVa         = true;           // Value Area markieren
input bool                  InpShowUnfinished = true;           // unvollendete Auktionen markieren
input bool                  InpShowInfo       = true;           // Kopfzeile oben links
input bool                  InpHideCandles    = true;           // Kerzen von MetaTrader ausblenden

//--- Ungleichgewichte ------------------------------------------------
input group                 "Ungleichgewichte"
input double                InpImbRatio       = 3.0;            // Verhaeltnis (3.0 = 300 Prozent)
input double                InpImbMinVol      = 4;              // Mindestvolumen einer Zelle
input int                   InpStackMin       = 3;              // Ebenen fuer eine Serie
input double                InpVaPercent      = 70;             // Value Area in Prozent

//--- Farben ----------------------------------------------------------
input group                 "Farben"
input color                 InpBull           = C'70,160,95';   // Kaufuebergewicht
input color                 InpBear           = C'214,80,80';   // Verkaufsuebergewicht
input color                 InpNeutral        = C'250,250,250'; // ausgeglichen
input color                 InpImbColor       = C'20,70,220';   // Zahl mit Ungleichgewicht
input color                 InpFrameColor     = C'10,10,10';    // Rahmen um Serien
input color                 InpPocColor       = C'120,120,120'; // Rahmen um den Point of Control
input color                 InpVaColor        = C'140,140,140'; // Streifen der Value Area
input color                 InpUnfColor       = C'255,140,0';   // unvollendete Auktion
input color                 InpInfoColor      = clrNONE;        // Kopfzeile (clrNONE = automatisch)

//--- Puffer fuer iCustom ---------------------------------------------
double BufDelta[];
double BufCum[];
double BufPoc[];
double BufVol[];
double BufSig[];

//--- Zustand ---------------------------------------------------------
CFpEngine g_engine;
CFpRender g_render;
FpStyle   g_style;
string    g_objName;
bool      g_ready      = false;
bool      g_dirty      = true;
uint      g_lastDraw   = 0;
bool      g_colorsSaved = false;
long      g_savedBull, g_savedBear, g_savedUp, g_savedDown, g_savedLine;

//+------------------------------------------------------------------+
//| Farben der Standardkerzen merken und abschalten                  |
//+------------------------------------------------------------------+
void HideNativeCandles(void)
  {
   if(g_colorsSaved)
      return;
   g_savedBull = ChartGetInteger(0, CHART_COLOR_CANDLE_BULL);
   g_savedBear = ChartGetInteger(0, CHART_COLOR_CANDLE_BEAR);
   g_savedUp   = ChartGetInteger(0, CHART_COLOR_CHART_UP);
   g_savedDown = ChartGetInteger(0, CHART_COLOR_CHART_DOWN);
   g_savedLine = ChartGetInteger(0, CHART_COLOR_CHART_LINE);
   g_colorsSaved = true;

   ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, clrNONE);
   ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, clrNONE);
   ChartSetInteger(0, CHART_COLOR_CHART_UP,    clrNONE);
   ChartSetInteger(0, CHART_COLOR_CHART_DOWN,  clrNONE);
   ChartSetInteger(0, CHART_COLOR_CHART_LINE,  clrNONE);
  }

//+------------------------------------------------------------------+
void RestoreNativeCandles(void)
  {
   if(!g_colorsSaved)
      return;
   ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, g_savedBull);
   ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, g_savedBear);
   ChartSetInteger(0, CHART_COLOR_CHART_UP,    g_savedUp);
   ChartSetInteger(0, CHART_COLOR_CHART_DOWN,  g_savedDown);
   ChartSetInteger(0, CHART_COLOR_CHART_LINE,  g_savedLine);
   g_colorsSaved = false;
  }

//+------------------------------------------------------------------+
//| Stil aus den Eingaben zusammenbauen                              |
//+------------------------------------------------------------------+
void SetupStyle(void)
  {
   g_style.mode           = InpMode;
   g_style.intensity      = InpIntensity;
   g_style.bull           = InpBull;
   g_style.bear           = InpBear;
   g_style.neutral        = InpNeutral;
   g_style.textDark       = C'25,25,25';
   g_style.textLight      = C'240,240,240';
   g_style.imb            = InpImbColor;
   g_style.frame          = InpFrameColor;
   g_style.poc            = InpPocColor;
   g_style.va             = InpVaColor;
   g_style.unfinished     = InpUnfColor;
   g_style.candleUp       = FpMix(InpBull, clrBlack, 0.25);
   g_style.candleDn       = FpMix(InpBear, clrBlack, 0.25);
   g_style.alpha          = (InpAlpha < 30 ? 30 : (InpAlpha > 255 ? 255 : InpAlpha));
   g_style.showCandle     = InpShowCandle;
   g_style.showHeadTop    = InpHeadTop;
   g_style.showHeadBottom = InpHeadBottom;
   g_style.showPoc        = InpShowPoc;
   g_style.showVa         = InpShowVa;
   g_style.showUnfinished = InpShowUnfinished;
   g_style.showInfo       = InpShowInfo;
   g_style.font           = (InpFont == "" ? "Consolas" : InpFont);
   g_style.fontMax        = (InpFontMax < 5 ? 5 : InpFontMax);
   g_style.fontMin        = (InpFontMin < 4 ? 4 : InpFontMin);
   if(g_style.fontMin > g_style.fontMax)
      g_style.fontMin = g_style.fontMax;
   g_style.gapX           = (InpGapX < 0 ? 0 : InpGapX);
   g_style.minCellH       = (InpMinCellHeight < 5 ? 5 : InpMinCellHeight);

   //--- Schriftfarbe der Kopfzeile an den Charthintergrund anpassen
   if(InpInfoColor == clrNONE)
     {
      color bg = (color)ChartGetInteger(0, CHART_COLOR_BACKGROUND);
      g_style.info = (FpLuma(bg) > 128 ? C'60,60,60' : C'220,220,220');
     }
   else
      g_style.info = InpInfoColor;
  }

//+------------------------------------------------------------------+
int OnInit(void)
  {
   SetIndexBuffer(0, BufDelta, INDICATOR_DATA);
   SetIndexBuffer(1, BufCum,   INDICATOR_DATA);
   SetIndexBuffer(2, BufPoc,   INDICATOR_DATA);
   SetIndexBuffer(3, BufVol,   INDICATOR_DATA);
   SetIndexBuffer(4, BufSig,   INDICATOR_DATA);
   ArraySetAsSeries(BufDelta, true);
   ArraySetAsSeries(BufCum,   true);
   ArraySetAsSeries(BufPoc,   true);
   ArraySetAsSeries(BufVol,   true);
   ArraySetAsSeries(BufSig,   true);
   for(int i = 0; i < 5; i++)
      PlotIndexSetDouble(i, PLOT_EMPTY_VALUE, 0.0);

   IndicatorSetString(INDICATOR_SHORTNAME, "BauBox Footprint");
   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);

   if(!g_engine.Init(_Symbol, (ENUM_TIMEFRAMES)Period(), InpTicksPerLevel, InpAutoLevels,
                     InpSource, InpQuotePrice, InpAllowM1, InpMaxBars))
     {
      Print("Footprint: Symbolangaben unbrauchbar, Indikator startet nicht.");
      return INIT_FAILED;
     }
   g_engine.SetAnalysis(InpImbRatio, InpImbMinVol, InpStackMin, InpVaPercent);

   SetupStyle();

   g_objName = "BauBoxFootprint_" + IntegerToString(ChartID());
   if(!g_render.Create(g_objName))
     {
      Print("Footprint: Leinwand konnte nicht angelegt werden.");
      return INIT_FAILED;
     }

   if(InpHideCandles)
      HideNativeCandles();

   g_ready = true;
   g_dirty = true;
   EventSetMillisecondTimer(80);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   g_ready = false;
   g_render.Destroy();
   g_engine.Clear();
   RestoreNativeCandles();
   ChartRedraw();
  }

//+------------------------------------------------------------------+
//| Sichtbaren Bereich bestimmen                                     |
//+------------------------------------------------------------------+
bool VisibleRange(int &from, int &to)
  {
   int bars = Bars(_Symbol, _Period);
   if(bars <= 1)
      return false;
   int first = (int)ChartGetInteger(0, CHART_FIRST_VISIBLE_BAR);
   int nvis  = (int)ChartGetInteger(0, CHART_VISIBLE_BARS);
   if(nvis <= 0)
      return false;
   if(first > bars - 1)
      first = bars - 1;
   from = first;
   to   = first - nvis + 1;
   if(to < 0)
      to = 0;
   if(from < to)
      from = to;
   //--- der Speicher begrenzt, wie weit nach links gerechnet wird
   int lim = (InpMaxBars < 5 ? 5 : InpMaxBars);
   if(from - to + 1 > lim)
      from = to + lim - 1;
   return true;
  }

//+------------------------------------------------------------------+
//| Serien-Signal einer Kerze: +1 aufwaerts, -1 abwaerts, 0 keines   |
//+------------------------------------------------------------------+
double StackSignal(CFpBar *b)
  {
   if(b == NULL)
      return 0.0;
   int up = 0, dn = 0;
   int n = b.Count();
   for(int i = 0; i < n; i++)
     {
      if((b.cells[i].flags & FP_F_STACK) == 0)
         continue;
      if((b.cells[i].flags & FP_F_ASK_IMB) != 0)
         up++;
      if((b.cells[i].flags & FP_F_BID_IMB) != 0)
         dn++;
     }
   if(up > dn)
      return 1.0;
   if(dn > up)
      return -1.0;
   return 0.0;
  }

//+------------------------------------------------------------------+
//| Neu zeichnen                                                     |
//+------------------------------------------------------------------+
void Refresh(void)
  {
   if(!g_ready)
      return;
   g_render.Sync();

   int from = 0, to = 0;
   if(!VisibleRange(from, to))
      return;

   int budget = (InpBudget < 1 ? 1 : InpBudget);
   int pending = g_engine.Ensure(from, to, budget);
   g_render.Draw(g_engine, g_style, _Symbol, (ENUM_TIMEFRAMES)Period(), from, to);

   g_lastDraw = GetTickCount();
   g_dirty    = (pending > 0);
  }

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
  {
   if(!g_ready)
      return rates_total;

   ArraySetAsSeries(time, true);

   g_dirty = true;
   if(GetTickCount() - g_lastDraw >= 60)
      Refresh();

   //--- Kennzahlen in die Puffer schreiben, damit sie ein Expert lesen kann
   int lim = (InpMaxBars < 5 ? 5 : InpMaxBars);
   if(lim > rates_total)
      lim = rates_total;
   for(int s = 0; s < lim; s++)
     {
      CFpBar *b = g_engine.Find(time[s]);
      if(b == NULL || !b.built || b.empty)
        {
         BufDelta[s] = 0.0;
         BufCum[s]   = 0.0;
         BufPoc[s]   = 0.0;
         BufVol[s]   = 0.0;
         BufSig[s]   = 0.0;
         continue;
        }
      BufDelta[s] = b.delta;
      BufCum[s]   = b.cumDelta;
      BufPoc[s]   = (b.pocIdx >= 0
                     ? g_engine.LevelLow(b.LevelAt(b.pocIdx)) + g_engine.LevelSize() * 0.5
                     : 0.0);
      BufVol[s]   = b.volume;
      BufSig[s]   = StackSignal(b);
     }
   for(int s = lim; s < rates_total; s++)
     {
      BufDelta[s] = 0.0;
      BufCum[s]   = 0.0;
      BufPoc[s]   = 0.0;
      BufVol[s]   = 0.0;
      BufSig[s]   = 0.0;
     }

   return rates_total;
  }

//+------------------------------------------------------------------+
void OnTimer(void)
  {
   if(!g_ready)
      return;
   if(g_dirty && (GetTickCount() - g_lastDraw) >= 60)
      Refresh();
  }

//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   if(id == CHARTEVENT_CHART_CHANGE)
      g_dirty = true;
  }
//+------------------------------------------------------------------+
