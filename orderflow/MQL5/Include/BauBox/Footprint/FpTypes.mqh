//+------------------------------------------------------------------+
//|                                                      FpTypes.mqh |
//|        BauBox Footprint - Datentypen und Auswertung einer Kerze  |
//+------------------------------------------------------------------+
#ifndef BAUBOX_FP_TYPES_MQH
#define BAUBOX_FP_TYPES_MQH

#include "FpUtil.mqh"

//+------------------------------------------------------------------+
//| Anzeigearten                                                     |
//+------------------------------------------------------------------+
enum ENUM_FP_MODE
  {
   FP_MODE_BIDASK  = 0,   // Bid x Ask
   FP_MODE_DELTA   = 1,   // Delta je Ebene
   FP_MODE_VOLUME  = 2,   // Volumen je Ebene
   FP_MODE_PROFILE = 3    // nur Volumenprofil
  };

//+------------------------------------------------------------------+
//| Woher die Zahlen kommen                                          |
//+------------------------------------------------------------------+
enum ENUM_FP_SOURCE
  {
   FP_SRC_AUTO   = 0,   // automatisch erkennen
   FP_SRC_TRADES = 1,   // echte Abschluesse (Boerse, Futures)
   FP_SRC_QUOTES = 2,   // Bid/Ask-Ticks (Forex, CFD)
   FP_SRC_M1     = 3    // Naeherung aus M1-Kerzen
  };

//+------------------------------------------------------------------+
//| Welcher Kurs eines Quote-Ticks die Preisebene bestimmt           |
//+------------------------------------------------------------------+
enum ENUM_FP_QPRICE
  {
   FP_QP_BID = 0,   // Bid (deckt sich mit den Kerzen)
   FP_QP_MID = 1,   // Mittelkurs
   FP_QP_ASK = 2    // Ask
  };

//+------------------------------------------------------------------+
//| Wonach sich die Farbstaerke einer Zelle richtet                  |
//+------------------------------------------------------------------+
enum ENUM_FP_INTENSITY
  {
   FP_INT_DELTA  = 0,   // nach Delta
   FP_INT_VOLUME = 1    // nach Volumen
  };

//--- Markierungen einer Zelle
#define FP_F_ASK_IMB  1    // Kauf-Ungleichgewicht (Ask-Seite)
#define FP_F_BID_IMB  2    // Verkauf-Ungleichgewicht (Bid-Seite)
#define FP_F_STACK    4    // gehoert zu einer Serie gestapelter Ungleichgewichte
#define FP_F_VA       8    // liegt in der Value Area

//+------------------------------------------------------------------+
//| Eine Preisebene innerhalb einer Kerze                            |
//+------------------------------------------------------------------+
struct FpCell
  {
   double            bid;     // am Bid gehandelt (aggressiver Verkauf)
   double            ask;     // am Ask gehandelt (aggressiver Kauf)
   int               flags;   // Markierungen, siehe FP_F_*
  };

//+------------------------------------------------------------------+
//| Footprint einer einzelnen Kerze                                  |
//+------------------------------------------------------------------+
class CFpBar
  {
public:
   datetime          time;          // Eroeffnungszeit der Kerze
   long              lmin;          // unterste belegte Preisebene
   long              lmax;          // oberste belegte Preisebene
   FpCell            cells[];       // Index 0 entspricht lmin
   //--- Kursdaten der Kerze
   double            open, high, low, close;
   //--- Kennzahlen
   double            volume;        // Summe aller Zellen
   double            delta;         // Ask minus Bid ueber die ganze Kerze
   double            cumDelta;      // aufsummiertes Delta bis einschliesslich dieser Kerze
   double            maxCellVol;    // groesstes Zellvolumen (Point of Control)
   double            maxAbsDelta;   // groesstes Zelldelta dem Betrag nach
   int               pocIdx;        // Index des Point of Control
   int               vaLo, vaHi;    // Grenzen der Value Area
   bool              unfHigh;       // unvollendete Auktion am Hoch
   bool              unfLow;        // unvollendete Auktion am Tief
   //--- Zustand des Aufbaus
   bool              built;         // schon einmal gefuellt
   bool              finished;      // Kerze ist zu, nichts kommt mehr nach
   bool              approx;        // aus M1 geschaetzt statt aus Ticks
   bool              empty;         // keine einzige Zelle belegt
   long              lastMsc;       // Zeitstempel des letzten verarbeiteten Ticks
   int               lastMscCnt;    // wie viele Ticks mit genau diesem Zeitstempel schon drin sind
   double            prevPx;        // letzter Referenzkurs fuer die Tickregel
   int               prevDir;       // letzte Richtung fuer die Tickregel
   int               tries;         // fehlgeschlagene Ladeversuche

                     CFpBar(const datetime t);

   int               Count(void)               { return ArraySize(cells); }
   double            CellVol(const int i)      { return cells[i].bid + cells[i].ask; }
   double            CellDelta(const int i)    { return cells[i].ask - cells[i].bid; }
   long              LevelAt(const int i)      { return lmin + i; }

   void              Clear(void);
   bool              EnsureLevel(const long lv);
   void              Add(const long lv, const double vol, const bool buy);
   void              Analyze(const double imbRatio, const double imbMin,
                             const int stackMin, const double vaPart);
  };

//+------------------------------------------------------------------+
//| Erzeugen                                                         |
//+------------------------------------------------------------------+
CFpBar::CFpBar(const datetime t)
  {
   time       = t;
   lmin       = 0;
   lmax       = -1;
   open       = 0.0;
   high       = 0.0;
   low        = 0.0;
   close      = 0.0;
   volume     = 0.0;
   delta      = 0.0;
   cumDelta   = 0.0;
   maxCellVol = 0.0;
   maxAbsDelta= 0.0;
   pocIdx     = -1;
   vaLo       = -1;
   vaHi       = -1;
   unfHigh    = false;
   unfLow     = false;
   built      = false;
   finished   = false;
   approx     = false;
   empty      = true;
   lastMsc    = 0;
   lastMscCnt = 0;
   prevPx     = 0.0;
   prevDir    = 0;
   tries      = 0;
  }

//+------------------------------------------------------------------+
//| Inhalt verwerfen, Kursdaten bleiben stehen                       |
//+------------------------------------------------------------------+
void CFpBar::Clear(void)
  {
   ArrayFree(cells);
   lmin        = 0;
   lmax        = -1;
   volume      = 0.0;
   delta       = 0.0;
   maxCellVol  = 0.0;
   maxAbsDelta = 0.0;
   pocIdx      = -1;
   vaLo        = -1;
   vaHi        = -1;
   unfHigh     = false;
   unfLow      = false;
   empty       = true;
   lastMsc     = 0;
   lastMscCnt  = 0;
   prevPx      = 0.0;
   prevDir     = 0;
  }

//+------------------------------------------------------------------+
//| Platz fuer eine Preisebene schaffen                              |
//+------------------------------------------------------------------+
bool CFpBar::EnsureLevel(const long lv)
  {
   int n = ArraySize(cells);
   if(n == 0)
     {
      if(ArrayResize(cells, 1) != 1)
         return false;
      cells[0].bid   = 0.0;
      cells[0].ask   = 0.0;
      cells[0].flags = 0;
      lmin = lv;
      lmax = lv;
      return true;
     }
   if(lv >= lmin && lv <= lmax)
      return true;

   //--- ein unplausibler Tick darf das Raster nicht sprengen
   long want = (lv < lmin) ? (lmax - lv + 1) : (lv - lmin + 1);
   if(want > 20000)
      return false;

   if(lv < lmin)
     {
      int add = (int)(lmin - lv);
      if(ArrayResize(cells, n + add) != n + add)
         return false;
      for(int i = n - 1; i >= 0; i--)
         cells[i + add] = cells[i];
      for(int i = 0; i < add; i++)
        {
         cells[i].bid   = 0.0;
         cells[i].ask   = 0.0;
         cells[i].flags = 0;
        }
      lmin = lv;
     }
   else
     {
      int add = (int)(lv - lmax);
      if(ArrayResize(cells, n + add) != n + add)
         return false;
      for(int i = 0; i < add; i++)
        {
         cells[n + i].bid   = 0.0;
         cells[n + i].ask   = 0.0;
         cells[n + i].flags = 0;
        }
      lmax = lv;
     }
   return true;
  }

//+------------------------------------------------------------------+
//| Volumen auf eine Seite einer Preisebene buchen                   |
//+------------------------------------------------------------------+
void CFpBar::Add(const long lv, const double vol, const bool buy)
  {
   if(vol <= 0.0)
      return;
   if(!EnsureLevel(lv))
      return;
   int i = (int)(lv - lmin);
   if(i < 0 || i >= ArraySize(cells))
      return;
   if(buy)
      cells[i].ask += vol;
   else
      cells[i].bid += vol;
   empty = false;
  }

//+------------------------------------------------------------------+
//| Kennzahlen, Ungleichgewichte, Value Area                         |
//+------------------------------------------------------------------+
void CFpBar::Analyze(const double imbRatio, const double imbMin,
                     const int stackMin, const double vaPart)
  {
   int n = ArraySize(cells);
   volume      = 0.0;
   delta       = 0.0;
   maxCellVol  = 0.0;
   maxAbsDelta = 0.0;
   pocIdx      = -1;
   vaLo        = -1;
   vaHi        = -1;
   unfHigh     = false;
   unfLow      = false;
   if(n <= 0)
      return;

   //--- Summen und Point of Control
   for(int i = 0; i < n; i++)
     {
      cells[i].flags = 0;
      double v = cells[i].bid + cells[i].ask;
      double d = cells[i].ask - cells[i].bid;
      volume += v;
      delta  += d;
      if(v > maxCellVol)
        {
         maxCellVol = v;
         pocIdx     = i;
        }
      if(MathAbs(d) > maxAbsDelta)
         maxAbsDelta = MathAbs(d);
     }

   //--- diagonale Ungleichgewichte: Ask gegen das Bid eine Ebene tiefer
   for(int i = 0; i < n; i++)
     {
      if(i > 0)
        {
         double a = cells[i].ask;
         double b = cells[i - 1].bid;
         if(a >= imbMin && (b <= 0.0 || a >= b * imbRatio))
            cells[i].flags |= FP_F_ASK_IMB;
        }
      if(i < n - 1)
        {
         double bb = cells[i].bid;
         double aa = cells[i + 1].ask;
         if(bb >= imbMin && (aa <= 0.0 || bb >= aa * imbRatio))
            cells[i].flags |= FP_F_BID_IMB;
        }
     }

   //--- Serien: mehrere gleichgerichtete Ungleichgewichte direkt uebereinander
   if(stackMin > 1)
     {
      for(int side = 0; side < 2; side++)
        {
         int mask = (side == 0 ? FP_F_ASK_IMB : FP_F_BID_IMB);
         int run  = 0;
         for(int i = 0; i <= n; i++)
           {
            bool hit = (i < n) && ((cells[i].flags & mask) != 0);
            if(hit)
               run++;
            else
              {
               if(run >= stackMin)
                  for(int k = i - run; k < i; k++)
                     cells[k].flags |= FP_F_STACK;
               run = 0;
              }
           }
        }
     }

   //--- Value Area: vom Point of Control aus in Paaren nach aussen
   if(pocIdx >= 0 && volume > 0.0)
     {
      int    lo     = pocIdx;
      int    hi     = pocIdx;
      double acc    = CellVol(pocIdx);
      double target = volume * vaPart;
      while(acc < target && (lo > 0 || hi < n - 1))
        {
         double up = 0.0;
         if(hi + 1 < n)
           {
            up = CellVol(hi + 1);
            if(hi + 2 < n)
               up += CellVol(hi + 2);
           }
         double dn = 0.0;
         if(lo - 1 >= 0)
           {
            dn = CellVol(lo - 1);
            if(lo - 2 >= 0)
               dn += CellVol(lo - 2);
           }
         if(hi < n - 1 && (up >= dn || lo <= 0))
           {
            hi++;
            acc += CellVol(hi);
            if(hi < n - 1 && acc < target)
              {
               hi++;
               acc += CellVol(hi);
              }
           }
         else
            if(lo > 0)
              {
               lo--;
               acc += CellVol(lo);
               if(lo > 0 && acc < target)
                 {
                  lo--;
                  acc += CellVol(lo);
                 }
              }
            else
               break;
        }
      vaLo = lo;
      vaHi = hi;
      for(int i = lo; i <= hi; i++)
         cells[i].flags |= FP_F_VA;
     }

   //--- unvollendete Auktion: am Extrem wurde auf beiden Seiten gehandelt
   unfHigh = (cells[n - 1].bid > 0.0 && cells[n - 1].ask > 0.0);
   unfLow  = (cells[0].bid    > 0.0 && cells[0].ask    > 0.0);
  }

#endif
