//+------------------------------------------------------------------+
//|                                                     FpEngine.mqh |
//|   BauBox Footprint - liest Ticks und baut daraus die Footprints  |
//+------------------------------------------------------------------+
#ifndef BAUBOX_FP_ENGINE_MQH
#define BAUBOX_FP_ENGINE_MQH

#include "FpTypes.mqh"

//+------------------------------------------------------------------+
//| Verwaltet alle bekannten Kerzen-Footprints eines Symbols         |
//+------------------------------------------------------------------+
class CFpEngine
  {
private:
   string            m_symbol;
   ENUM_TIMEFRAMES   m_tf;
   double            m_tick;        // kleinster Kursschritt
   int               m_perLevel;    // Ticks je Preisebene
   double            m_levelSize;   // Hoehe einer Preisebene im Kurs
   ENUM_FP_SOURCE    m_cfgSrc;      // gewuenschte Quelle
   ENUM_FP_SOURCE    m_src;         // tatsaechlich benutzte Quelle
   bool              m_srcFixed;    // Erkennung abgeschlossen
   ENUM_FP_QPRICE    m_qprice;
   bool              m_allowM1;
   int               m_maxBars;
   double            m_imbRatio;
   double            m_imbMin;
   int               m_stackMin;
   double            m_vaPart;
   CFpBar           *m_bars[];
   MqlTick           m_ticks[];
   int               m_pending;     // noch nicht fertige Kerzen im Sichtbereich
   int               m_probes;      // Versuche, die Quelle zu erkennen
   bool              m_autoOpen;    // Rastergroesse noch offen
   int               m_autoTarget;  // angepeilte Ebenen je Kerze

   int               LowerBound(const datetime t);
   bool              BuildFromTicks(CFpBar *b);
   bool              BuildFromM1(CFpBar *b);
   bool              BarHasVolume(const datetime t);
   void              Prune(const datetime keepFrom, const datetime keepTo);
   void              Probe(void);

public:
                     CFpEngine(void);
                    ~CFpEngine(void);

   bool              Init(const string sym, const ENUM_TIMEFRAMES tf,
                          const int perLevel, const int autoLevels,
                          const ENUM_FP_SOURCE src, const ENUM_FP_QPRICE qp,
                          const bool allowM1, const int maxBars);
   void              SetAnalysis(const double imbRatio, const double imbMin,
                                 const int stackMin, const double vaPercent);
   void              Clear(void);

   long              PriceToLevel(const double p);
   double            LevelLow(const long lv)   { return (double)(lv * (long)m_perLevel) * m_tick; }
   double            LevelSize(void)           { return m_levelSize; }
   int               TicksPerLevel(void)       { return m_perLevel; }
   double            TickSize(void)            { return m_tick; }
   ENUM_FP_SOURCE    Source(void)              { return m_src; }
   int               Pending(void)             { return m_pending; }
   int               BarCount(void)            { return ArraySize(m_bars); }

   CFpBar           *Find(const datetime t);
   CFpBar           *Obtain(const datetime t);
   int               Ensure(const int shiftFrom, const int shiftTo, int budget);
   void              RecalcCumulative(void);
   int               AutoPerLevel(const int targetLevels);
   string            SourceText(void);
  };

//+------------------------------------------------------------------+
CFpEngine::CFpEngine(void)
  {
   m_symbol    = "";
   m_tf        = PERIOD_CURRENT;
   m_tick      = 1.0;
   m_perLevel  = 1;
   m_levelSize = 1.0;
   m_cfgSrc    = FP_SRC_AUTO;
   m_src       = FP_SRC_QUOTES;
   m_srcFixed  = false;
   m_qprice    = FP_QP_BID;
   m_allowM1   = true;
   m_maxBars   = 120;
   m_imbRatio  = 3.0;
   m_imbMin    = 1.0;
   m_stackMin  = 3;
   m_vaPart    = 0.7;
   m_pending   = 0;
   m_probes    = 0;
   m_autoOpen  = false;
   m_autoTarget= 16;
  }

//+------------------------------------------------------------------+
CFpEngine::~CFpEngine(void)
  {
   Clear();
  }

//+------------------------------------------------------------------+
//| Alle zwischengespeicherten Kerzen freigeben                      |
//+------------------------------------------------------------------+
void CFpEngine::Clear(void)
  {
   int n = ArraySize(m_bars);
   for(int i = 0; i < n; i++)
      if(CheckPointer(m_bars[i]) == POINTER_DYNAMIC)
         delete m_bars[i];
   ArrayFree(m_bars);
   m_pending = 0;
  }

//+------------------------------------------------------------------+
//| Grundeinstellungen setzen                                        |
//+------------------------------------------------------------------+
bool CFpEngine::Init(const string sym, const ENUM_TIMEFRAMES tf,
                     const int perLevel, const int autoLevels,
                     const ENUM_FP_SOURCE src, const ENUM_FP_QPRICE qp,
                     const bool allowM1, const int maxBars)
  {
   Clear();
   m_symbol = sym;
   m_tf     = (tf == PERIOD_CURRENT ? (ENUM_TIMEFRAMES)Period() : tf);

   m_tick = SymbolInfoDouble(m_symbol, SYMBOL_TRADE_TICK_SIZE);
   if(m_tick <= 0.0)
      m_tick = SymbolInfoDouble(m_symbol, SYMBOL_POINT);
   if(m_tick <= 0.0)
      m_tick = 0.00001;

   m_cfgSrc   = src;
   m_srcFixed = (src != FP_SRC_AUTO);
   m_src      = (src == FP_SRC_AUTO ? FP_SRC_QUOTES : src);
   m_qprice   = qp;
   m_allowM1  = allowM1;
   m_maxBars  = (maxBars < 5 ? 5 : maxBars);

   m_autoTarget = (autoLevels > 2 ? autoLevels : 16);
   m_autoOpen   = false;
   if(perLevel > 0)
      m_perLevel = perLevel;
   else
     {
      m_perLevel = AutoPerLevel(m_autoTarget);
      if(m_perLevel < 1)
        {
         //--- Historie noch nicht geladen: vorlaeufiges Raster, wird in
         //    Ensure() korrigiert, sobald Kerzen da sind
         m_perLevel = 1;
         m_autoOpen = true;
        }
     }
   m_levelSize = m_tick * m_perLevel;
   return (m_levelSize > 0.0);
  }

//+------------------------------------------------------------------+
void CFpEngine::SetAnalysis(const double imbRatio, const double imbMin,
                            const int stackMin, const double vaPercent)
  {
   m_imbRatio = (imbRatio < 1.0 ? 1.0 : imbRatio);
   m_imbMin   = (imbMin   < 0.0 ? 0.0 : imbMin);
   m_stackMin = (stackMin < 1   ? 1   : stackMin);
   m_vaPart   = vaPercent / 100.0;
   if(m_vaPart <= 0.0 || m_vaPart > 1.0)
      m_vaPart = 0.7;
  }

//+------------------------------------------------------------------+
//| Kurs auf eine Preisebene abbilden                                |
//+------------------------------------------------------------------+
long CFpEngine::PriceToLevel(const double p)
  {
   long t = (long)MathRound(p / m_tick);
   double q = (double)t / (double)m_perLevel;
   return (long)MathFloor(q);
  }

//+------------------------------------------------------------------+
//| Passende Rastergroesse aus der mittleren Kerzenhoehe ableiten    |
//+------------------------------------------------------------------+
int CFpEngine::AutoPerLevel(const int targetLevels)
  {
   MqlRates r[];
   int startPos = 0;
   int wanted   = 60;
   int n = CopyRates(m_symbol, m_tf, startPos, wanted, r);
   if(n <= 0)
      return 0;                 // Historie noch nicht da, spaeter erneut

   double sum = 0.0;
   int    cnt = 0;
   for(int i = 0; i < n; i++)
     {
      double rng = r[i].high - r[i].low;
      if(rng > 0.0)
        {
         sum += rng;
         cnt++;
        }
     }
   if(cnt == 0)
      return 0;

   double avgTicks = (sum / cnt) / m_tick;
   double want     = avgTicks / (double)targetLevels;
   if(want <= 1.0)
      return 1;

   //--- auf eine runde Zahl ziehen, damit das Raster lesbar bleibt
   int nice[] = {1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 25000, 50000};
   int best   = nice[0];
   for(int i = 0; i < ArraySize(nice); i++)
     {
      if((double)nice[i] <= want)
         best = nice[i];
      else
         break;
     }
   return best;
  }

//+------------------------------------------------------------------+
//| Position der ersten Kerze mit Zeit >= t                          |
//+------------------------------------------------------------------+
int CFpEngine::LowerBound(const datetime t)
  {
   int lo = 0;
   int hi = ArraySize(m_bars);
   while(lo < hi)
     {
      int mid = (lo + hi) / 2;
      if(m_bars[mid].time < t)
         lo = mid + 1;
      else
         hi = mid;
     }
   return lo;
  }

//+------------------------------------------------------------------+
CFpBar *CFpEngine::Find(const datetime t)
  {
   int n = ArraySize(m_bars);
   int p = LowerBound(t);
   if(p < n && m_bars[p].time == t)
      return m_bars[p];
   return NULL;
  }

//+------------------------------------------------------------------+
//| Kerze holen, bei Bedarf anlegen (Liste bleibt nach Zeit sortiert)|
//+------------------------------------------------------------------+
CFpBar *CFpEngine::Obtain(const datetime t)
  {
   int n = ArraySize(m_bars);
   int p = LowerBound(t);
   if(p < n && m_bars[p].time == t)
      return m_bars[p];

   CFpBar *b = new CFpBar(t);
   if(b == NULL)
      return NULL;
   if(ArrayResize(m_bars, n + 1) != n + 1)
     {
      delete b;
      return NULL;
     }
   for(int i = n; i > p; i--)
      m_bars[i] = m_bars[i - 1];
   m_bars[p] = b;
   return b;
  }

//+------------------------------------------------------------------+
//| Aufraeumen. Behalten wird, was im Sichtfenster liegt - sonst     |
//| wuerde beim Blaettern nach links genau das geloescht, was gerade |
//| gebraucht wird.                                                  |
//+------------------------------------------------------------------+
void CFpEngine::Prune(const datetime keepFrom, const datetime keepTo)
  {
   int n = ArraySize(m_bars);
   if(n <= m_maxBars * 2)
      return;
   int w = 0;
   for(int i = 0; i < n; i++)
     {
      if(m_bars[i].time >= keepFrom && m_bars[i].time <= keepTo)
        {
         m_bars[w] = m_bars[i];
         w++;
        }
      else
         if(CheckPointer(m_bars[i]) == POINTER_DYNAMIC)
            delete m_bars[i];
     }
   ArrayResize(m_bars, w);
  }

//+------------------------------------------------------------------+
//| Einmalige Stichprobe: liefert das Symbol echte Abschluesse mit   |
//| Kaeufer- und Verkaeuferkennung, oder nur Bid/Ask-Quotes?         |
//+------------------------------------------------------------------+
void CFpEngine::Probe(void)
  {
   if(m_srcFixed)
      return;
   m_probes++;
   if(m_probes > 80)
     {
      m_srcFixed = true;      // aufgeben, bei Quotes bleiben
      return;
     }

   datetime now  = TimeCurrent();
   ulong    to   = (ulong)((long)now * 1000);
   ulong    from = (ulong)(((long)now - 86400) * 1000);

   MqlTick probe[];
   ResetLastError();
   int n = CopyTicksRange(m_symbol, probe, COPY_TICKS_ALL, from, to);
   ResetLastError();
   if(n < 50)
      return;                  // noch zu wenig Material

   int trades = 0;
   for(int i = 0; i < n; i++)
      if((probe[i].flags & TICK_FLAG_LAST) != 0 && probe[i].last > 0.0 &&
         (probe[i].volume > 0 || probe[i].volume_real > 0.0))
         trades++;

   ENUM_FP_SOURCE found = (trades * 20 >= n ? FP_SRC_TRADES : FP_SRC_QUOTES);
   if(found != m_src)
     {
      m_src = found;
      Clear();                 // schon Gerechnetes war nach der falschen Regel
     }
   m_srcFixed = true;
  }

//+------------------------------------------------------------------+
//| Hatte die Kerze ueberhaupt Umsatz? Unterscheidet "keine Ticks    |
//| geladen" von "in dieser Minute passierte nichts".                |
//+------------------------------------------------------------------+
bool CFpEngine::BarHasVolume(const datetime t)
  {
   MqlRates r[];
   if(CopyRates(m_symbol, m_tf, t, t, r) != 1)
      return false;
   return (r[0].tick_volume > 0 || r[0].real_volume > 0);
  }

//+------------------------------------------------------------------+
//| Kerze aus Ticks aufbauen oder fortschreiben                      |
//+------------------------------------------------------------------+
bool CFpEngine::BuildFromTicks(CFpBar *b)
  {
   datetime t0   = b.time;
   int      secs = PeriodSeconds(m_tf);
   datetime t1   = (datetime)((long)t0 + secs);

   //--- Kursdaten der Kerze nachziehen
   MqlRates r[];
   if(CopyRates(m_symbol, m_tf, t0, t0, r) == 1)
     {
      b.open  = r[0].open;
      b.high  = r[0].high;
      b.low   = r[0].low;
      b.close = r[0].close;
     }

   bool  incr = (b.lastMsc > 0);
   ulong from = (ulong)((long)t0 * 1000);
   ulong to   = (ulong)((long)t1 * 1000 - 1);
   if(incr)
      from = (ulong)b.lastMsc;

   ResetLastError();
   int copied = CopyTicksRange(m_symbol, m_ticks, COPY_TICKS_ALL, from, to);
   if(copied < 0)
     {
      //--- Tickhistorie wird im Hintergrund geladen, spaeter erneut versuchen
      b.tries++;
      ResetLastError();
      if(b.tries > 40 && m_allowM1)
         return BuildFromM1(b);
      return false;
     }

   if(copied == 0 && !incr)
     {
      if(m_allowM1 && BarHasVolume(t0))
         return BuildFromM1(b);
      b.built = true;
      if(TimeCurrent() >= t1)
         b.finished = true;
      return true;
     }

   //--- beim Vollaufbau alles verwerfen, sonst wuerde doppelt gezaehlt
   if(!incr)
      b.Clear();

   //--- beim Fortschreiben die schon verarbeiteten Ticks derselben Millisekunde ueberspringen
   int start = 0;
   if(incr)
     {
      int same = 0;
      while(start < copied && (long)m_ticks[start].time_msc == b.lastMsc && same < b.lastMscCnt)
        {
         start++;
         same++;
        }
     }

   //--- Ticks einsortieren
   for(int i = start; i < copied; i++)
     {
      double px  = 0.0;
      double ref = 0.0;
      double vol = 0.0;
      bool   buy = true;

      if(m_src == FP_SRC_TRADES)
        {
         if((m_ticks[i].flags & TICK_FLAG_LAST) == 0)
            continue;
         px = m_ticks[i].last;
         if(px <= 0.0)
            continue;
         vol = (m_ticks[i].volume_real > 0.0 ? m_ticks[i].volume_real : (double)m_ticks[i].volume);
         if(vol <= 0.0)
            vol = 1.0;

         if((m_ticks[i].flags & TICK_FLAG_BUY) != 0)
            buy = true;
         else
            if((m_ticks[i].flags & TICK_FLAG_SELL) != 0)
               buy = false;
            else
               if(m_ticks[i].ask > 0.0 && px >= m_ticks[i].ask)
                  buy = true;
               else
                  if(m_ticks[i].bid > 0.0 && px <= m_ticks[i].bid)
                     buy = false;
                  else
                     buy = (px > b.prevPx ? true : (px < b.prevPx ? false : (b.prevDir >= 0)));
         ref = px;
        }
      else
        {
         if((m_ticks[i].flags & (TICK_FLAG_BID | TICK_FLAG_ASK)) == 0)
            continue;
         double bid = m_ticks[i].bid;
         double ask = m_ticks[i].ask;
         if(bid <= 0.0 && ask <= 0.0)
            continue;
         if(bid <= 0.0)
            bid = ask;
         if(ask <= 0.0)
            ask = bid;
         double mid = (bid + ask) * 0.5;
         px  = (m_qprice == FP_QP_BID ? bid : (m_qprice == FP_QP_ASK ? ask : mid));
         ref = mid;
         vol = (m_ticks[i].volume_real > 0.0 ? m_ticks[i].volume_real : 1.0);
         buy = (mid > b.prevPx ? true : (mid < b.prevPx ? false : (b.prevDir >= 0)));
        }

      b.prevPx  = ref;
      b.prevDir = (buy ? 1 : -1);
      b.Add(PriceToLevel(px), vol, buy);
     }

   if(copied > 0)
     {
      b.lastMsc = (long)m_ticks[copied - 1].time_msc;
      int c = 0;
      for(int i = copied - 1; i >= 0 && (long)m_ticks[i].time_msc == b.lastMsc; i--)
         c++;
      b.lastMscCnt = c;
     }

   b.built  = true;
   b.approx = false;
   b.tries  = 0;
   if(TimeCurrent() >= t1)
      b.finished = true;
   b.Analyze(m_imbRatio, m_imbMin, m_stackMin, m_vaPart);
   return true;
  }

//+------------------------------------------------------------------+
//| Notloesung ohne Tickhistorie: Volumen der M1-Kerzen verteilen.   |
//| Das ist eine Schaetzung und wird im Chart als solche markiert.   |
//+------------------------------------------------------------------+
bool CFpEngine::BuildFromM1(CFpBar *b)
  {
   datetime t0 = b.time;
   int      secs = PeriodSeconds(m_tf);
   datetime t1 = (datetime)((long)t0 + secs);

   MqlRates r[];
   int n = CopyRates(m_symbol, PERIOD_M1, t0, (datetime)((long)t1 - 1), r);
   if(n <= 0)
     {
      b.tries++;
      return false;
     }

   b.Clear();
   for(int i = 0; i < n; i++)
     {
      double vol = (r[i].real_volume > 0 ? (double)r[i].real_volume : (double)r[i].tick_volume);
      if(vol <= 0.0)
         continue;
      long l0 = PriceToLevel(r[i].low);
      long l1 = PriceToLevel(r[i].high);
      if(l1 < l0)
        {
         long tmp = l0;
         l0 = l1;
         l1 = tmp;
        }
      int cnt = (int)(l1 - l0 + 1);
      if(cnt < 1 || cnt > 5000)
         continue;
      double share = vol / cnt;
      double up    = (r[i].close > r[i].open ? 0.65 : (r[i].close < r[i].open ? 0.35 : 0.5));
      for(long lv = l0; lv <= l1; lv++)
        {
         b.Add(lv, share * up,         true);
         b.Add(lv, share * (1.0 - up), false);
        }
     }

   MqlRates rb[];
   if(CopyRates(m_symbol, m_tf, t0, t0, rb) == 1)
     {
      b.open  = rb[0].open;
      b.high  = rb[0].high;
      b.low   = rb[0].low;
      b.close = rb[0].close;
     }

   b.built  = true;
   b.approx = true;
   b.tries  = 0;
   if(TimeCurrent() >= t1)
      b.finished = true;
   b.Analyze(m_imbRatio, m_imbMin, m_stackMin, m_vaPart);
   return true;
  }

//+------------------------------------------------------------------+
//| Sichtbaren Bereich aufbauen. budget begrenzt die Arbeit je Aufruf|
//| damit das Terminal nicht stehen bleibt. Rueckgabe: offene Kerzen.|
//+------------------------------------------------------------------+
int CFpEngine::Ensure(const int shiftFrom, const int shiftTo, int budget)
  {
   //--- Rastergroesse nachholen, sobald genug Historie da ist
   if(m_autoOpen)
     {
      int per = AutoPerLevel(m_autoTarget);
      if(per > 0)
        {
         m_autoOpen = false;
         if(per != m_perLevel)
           {
            m_perLevel  = per;
            m_levelSize = m_tick * m_perLevel;
            Clear();            // altes Raster passt nicht mehr
           }
        }
     }

   Probe();

   m_pending = 0;
   int from = (shiftFrom > shiftTo ? shiftFrom : shiftTo);
   int to   = (shiftTo   < shiftFrom ? shiftTo : shiftFrom);
   if(to < 0)
      to = 0;

   //--- von der juengsten Kerze nach links, damit der rechte Rand zuerst steht
   for(int s = to; s <= from; s++)
     {
      datetime t = iTime(m_symbol, m_tf, s);
      if(t == 0)
         continue;
      CFpBar *b = Obtain(t);
      if(b == NULL)
         continue;
      if(b.built && b.finished)
         continue;
      if(budget <= 0)
        {
         m_pending++;
         continue;
        }
      budget--;
      bool ok = (m_src == FP_SRC_M1 ? BuildFromM1(b) : BuildFromTicks(b));
      if(!ok)
         m_pending++;
     }

   datetime keepTo   = iTime(m_symbol, m_tf, to);
   datetime keepFrom = iTime(m_symbol, m_tf, from);
   if(keepTo == 0)
      keepTo = TimeCurrent();
   if(keepFrom > 0 && keepTo >= keepFrom)
      Prune(keepFrom, keepTo);

   RecalcCumulative();
   return m_pending;
  }

//+------------------------------------------------------------------+
//| Kumuliertes Delta ueber alle gespeicherten Kerzen                |
//+------------------------------------------------------------------+
void CFpEngine::RecalcCumulative(void)
  {
   double c = 0.0;
   int    n = ArraySize(m_bars);
   for(int i = 0; i < n; i++)
     {
      c += m_bars[i].delta;
      m_bars[i].cumDelta = c;
     }
  }

//+------------------------------------------------------------------+
string CFpEngine::SourceText(void)
  {
   switch(m_src)
     {
      case FP_SRC_TRADES:
         return "echte Abschluesse";
      case FP_SRC_M1:
         return "M1-Naeherung";
      default:
         break;
     }
   string p = (m_qprice == FP_QP_BID ? "Bid" : (m_qprice == FP_QP_ASK ? "Ask" : "Mitte"));
   return "Bid/Ask-Ticks (" + p + ")";
  }

#endif
