//+------------------------------------------------------------------+
//|                                                     Dreizack.mq5 |
//|                                                           BauBox |
//|                                                                  |
//| Werkzeugleiste fuer Price Action in MetaTrader 5.                |
//|                                                                  |
//|   - Rechtecke MIT Alarm  (6 Farben)                              |
//|   - Rechtecke OHNE Alarm (4 Farben)                              |
//|   - Dreizack             (4 Farben) mit den Stufen 1, 2 und 3    |
//|   - Trendlinien          (4 Farben)                              |
//|   - Fenster oben rechts: Kerzenrestzeit, auf Klick die laufende  |
//|     Handelssession samt Zeitspanne                               |
//|   - Taste zum Ein- und Ausklappen der Leiste                     |
//|                                                                  |
//| Der Alarm gilt ausschliesslich fuer die Rechtecke aus der ersten |
//| Gruppe. Rechtecke aus der zweiten Gruppe und alles, was von Hand |
//| in MetaTrader gezeichnet wurde, bleibt stumm.                    |
//+------------------------------------------------------------------+
#property copyright "BauBox"
#property link      "https://github.com/TwiTra/BauBox"
#property version   "1.00"
#property description "Dreizack: Rechtecke mit und ohne Alarm, Dreizack mit Stufe 1/2/3, Trendlinien, Kerzenzeit und Session"
#property indicator_chart_window

#include <BauBox\Dreizack\DzTypes.mqh>
#include <BauBox\Dreizack\DzUtil.mqh>
#include <BauBox\Dreizack\DzSession.mqh>
#include <BauBox\Dreizack\DzPanel.mqh>
#include <BauBox\Dreizack\DzTools.mqh>
#include <BauBox\Dreizack\DzAlarm.mqh>

//--- Leiste ----------------------------------------------------------
input group                "Leiste"
input ENUM_DZ_CORNER  InpCorner      = DZ_CORNER_RU;        // Ecke, an der die Leiste klebt
input int             InpMarginX     = 8;                   // Abstand zum Rand, waagerecht
input int             InpMarginY     = 18;                  // Abstand zum Rand, senkrecht
input int             InpScale       = 100;                 // Massstab in Prozent
input string          InpFont        = "Arial";             // Schrift der Leiste
input color           InpPanelBg     = C'238,238,238';      // Flaeche der Leiste
input color           InpPanelEdge   = C'150,150,150';      // Rand der Leiste
input color           InpPanelInk    = C'40,40,40';         // Schrift der Leiste
input bool            InpMiniKeepTmr = true;                // eingeklappt: Fenster weiter zeigen

//--- Fenster oben rechts ---------------------------------------------
input group                "Fenster oben rechts"
input color           InpTimerBg     = C'68,114,196';       // Flaeche des Fensters
input color           InpTimerInk    = C'255,255,255';      // Schrift im Fenster
input ENUM_DZ_TIMERMODE InpTimerStart = DZ_TM_CANDLE;       // Anzeige beim Start

//--- Farben der Tasten -----------------------------------------------
input group                "Farben - Rechtecke MIT Alarm"
input color           InpAl1 = C'112,173,71';               // Alarm 1
input color           InpAl2 = C'91,155,213';               // Alarm 2
input color           InpAl3 = C'237,125,49';               // Alarm 3
input color           InpAl4 = C'255,192,0';                // Alarm 4
input color           InpAl5 = C'214,45,45';                // Alarm 5
input color           InpAl6 = C'112,48,160';               // Alarm 6

input group                "Farben - Rechtecke ohne Alarm"
input color           InpRc1 = C'91,155,213';               // Rechteck 1
input color           InpRc2 = C'146,208,80';               // Rechteck 2
input color           InpRc3 = C'244,177,131';              // Rechteck 3
input color           InpRc4 = C'204,102,255';              // Rechteck 4

input group                "Farben - Dreizack"
input color           InpFk1 = C'91,155,213';               // Dreizack 1
input color           InpFk2 = C'112,173,71';               // Dreizack 2
input color           InpFk3 = C'255,205,80';               // Dreizack 3
input color           InpFk4 = C'204,102,255';              // Dreizack 4

input group                "Farben - Trendlinien"
input color           InpLn1 = C'91,155,213';               // Trendlinie 1
input color           InpLn2 = C'112,173,71';               // Trendlinie 2
input color           InpLn3 = C'237,125,49';               // Trendlinie 3
input color           InpLn4 = C'176,112,224';              // Trendlinie 4

//--- Rechtecke und Linien --------------------------------------------
input group                "Rechtecke und Linien"
input bool            InpRectFill    = true;                // Rechteck ausfuellen
input bool            InpRectBack    = true;                // hinter den Kerzen zeichnen
input int             InpRectWidth   = 1;                   // Randstaerke ohne Alarm
input int             InpRectWidthAl = 2;                   // Randstaerke mit Alarm
input int             InpLineWidth   = 1;                   // Staerke der Trendlinie
input bool            InpLineRay     = false;               // Trendlinie nach rechts verlaengern

//--- Dreizack ---------------------------------------------------------
input group                "Dreizack"
input ENUM_DZ_FORKMODE InpForkMode   = DZ_FORK_3CLICK;      // Setzen per drei Klicks oder automatisch
input int             InpForkAutoBars = 30;                 // automatisch: Suchfenster in Kerzen
input ENUM_DZ_BASE    InpForkBase    = DZ_BASE_C;           // Stufen messen ab
input double          InpForkF1      = 1.0;                 // Stufe 1 = Faktor x Impuls
input double          InpForkF2      = 2.0;                 // Stufe 2 = Faktor x Impuls  (sicherer Bereich)
input double          InpForkF3      = 3.0;                 // Stufe 3 = Faktor x Impuls  (Ende der Bewegung)
input int             InpForkLevBars = 60;                  // Laenge einer Stufe in Kerzen
input int             InpForkFanBars = 0;                   // Vorlauf je Zinke in Kerzen (0 = aus der Impulsdauer)
input bool            InpForkRay     = false;               // Stufen endlos nach rechts
input int             InpForkLegW    = 1;                   // Staerke der Schenkel
input int             InpForkLevW    = 1;                   // Grundstaerke der Stufen
input bool            InpForkEmph    = true;                // Stufe 2 und 3 hervorheben
input color           InpForkLevCol  = clrNONE;             // Farbe der Stufen (clrNONE = wie der Dreizack)
input bool            InpForkBox     = true;                // gestrichelte Box um die Basis
input color           InpForkBoxCol  = C'0,190,120';        // Farbe der Basisbox
input bool            InpForkPrice   = false;               // Preis neben die Stufennummer
input ENUM_DZ_INFO    InpForkInfo    = DZ_INFO_BARS_POINTS; // Messtext an der Spitze
input int             InpForkFontSz  = 8;                   // Schriftgroesse am Dreizack

//--- Alarm ------------------------------------------------------------
input group                "Alarm (nur Rechtecke aus der Alarmgruppe)"
input bool            InpAlarmOn     = true;                // Alarm eingeschaltet
input ENUM_DZ_TRIGGER InpAlarmTrig   = DZ_TRIG_TOUCH;       // ausloesen bei
input bool            InpAlarmTimeBox = false;              // nur innerhalb der Zeitspanne des Rechtecks
input bool            InpAlarmRepeat = true;                // bei jedem neuen Eintritt erneut melden
input int             InpAlarmCool   = 60;                  // Sperrzeit je Zone in Sekunden
input bool            InpAlarmPopup  = true;                // Fenster mit Meldung
input bool            InpAlarmSound  = true;                // Ton abspielen
input string          InpAlarmWav    = "alert2.wav";        // Tondatei
input bool            InpAlarmPush   = false;               // Push aufs Telefon
input bool            InpAlarmMail   = false;               // E-Mail
input bool            InpAlarmMark   = true;                // ausgeloeste Zone gestrichelt zeichnen

//--- Handelssessions --------------------------------------------------
input group                "Handelssessions (Zeiten in GMT)"
input bool            InpGmtAuto     = true;                // Serverzeit gegen GMT selbst bestimmen
input int             InpGmtOffset   = 2;                   // sonst: Server minus GMT in Stunden
input string          InpS1Name      = "Sydney";            // Session 1 Name
input string          InpS1Span      = "22:00-07:00";       // Session 1 Zeitspanne
input color           InpS1Col       = C'240,180,60';       // Session 1 Farbe
input bool            InpS1On        = true;                // Session 1 benutzen
input string          InpS2Name      = "Tokio";             // Session 2 Name
input string          InpS2Span      = "00:00-09:00";       // Session 2 Zeitspanne
input color           InpS2Col       = C'230,110,110';      // Session 2 Farbe
input bool            InpS2On        = true;                // Session 2 benutzen
input string          InpS3Name      = "London";            // Session 3 Name
input string          InpS3Span      = "08:00-17:00";       // Session 3 Zeitspanne
input color           InpS3Col       = C'110,190,120';      // Session 3 Farbe
input bool            InpS3On        = true;                // Session 3 benutzen
input string          InpS4Name      = "New York";          // Session 4 Name
input string          InpS4Span      = "13:00-22:00";       // Session 4 Zeitspanne
input color           InpS4Col       = C'110,160,230';      // Session 4 Farbe
input bool            InpS4On        = true;                // Session 4 benutzen

//--- Sonstiges --------------------------------------------------------
input group                "Sonstiges"
input bool            InpClearOnRemove = false;             // Zeichnungen beim Entfernen loeschen

//--- Zustand
datetime g_lastBarTime = 0;

//+------------------------------------------------------------------+
//| Eingaben in die Arbeitsvariablen der Module uebernehmen          |
//+------------------------------------------------------------------+
void DzApplyInputs(void)
  {
   //--- Leiste
   switch(InpCorner)
     {
      case DZ_CORNER_LU: g_dzCorner = (int)CORNER_LEFT_UPPER;  break;
      case DZ_CORNER_RL: g_dzCorner = (int)CORNER_RIGHT_LOWER; break;
      case DZ_CORNER_LL: g_dzCorner = (int)CORNER_LEFT_LOWER;  break;
      default:           g_dzCorner = (int)CORNER_RIGHT_UPPER; break;
     }
   g_dzMarginX     = (InpMarginX < 0 ? 0 : InpMarginX);
   g_dzMarginY     = (InpMarginY < 0 ? 0 : InpMarginY);
   g_dzScale       = (InpScale < 60 ? 60 : (InpScale > 250 ? 250 : InpScale));
   g_dzFont        = (InpFont == "" ? "Arial" : InpFont);
   g_dzPanelBg     = InpPanelBg;
   g_dzPanelEdge   = InpPanelEdge;
   g_dzPanelInk    = InpPanelInk;
   g_dzTimerBg     = InpTimerBg;
   g_dzTimerInk    = InpTimerInk;
   g_dzMiniKeepTmr = InpMiniKeepTmr;

   //--- Tastenfarben
   g_dzColAlarm[0] = InpAl1; g_dzColAlarm[1] = InpAl2; g_dzColAlarm[2] = InpAl3;
   g_dzColAlarm[3] = InpAl4; g_dzColAlarm[4] = InpAl5; g_dzColAlarm[5] = InpAl6;
   g_dzColRect[0]  = InpRc1; g_dzColRect[1]  = InpRc2;
   g_dzColRect[2]  = InpRc3; g_dzColRect[3]  = InpRc4;
   g_dzColFork[0]  = InpFk1; g_dzColFork[1]  = InpFk2;
   g_dzColFork[2]  = InpFk3; g_dzColFork[3]  = InpFk4;
   g_dzColLine[0]  = InpLn1; g_dzColLine[1]  = InpLn2;
   g_dzColLine[2]  = InpLn3; g_dzColLine[3]  = InpLn4;

   //--- Rechtecke und Linien
   g_rcFill     = InpRectFill;
   g_rcBack     = InpRectBack;
   g_rcWidth    = (InpRectWidth   < 1 ? 1 : InpRectWidth);
   g_rcAlarmWid = (InpRectWidthAl < 1 ? 1 : InpRectWidthAl);
   g_lnWidth    = (InpLineWidth   < 1 ? 1 : InpLineWidth);
   g_lnRay      = InpLineRay;

   //--- Dreizack
   g_fkMode      = InpForkMode;
   g_fkBase      = InpForkBase;
   g_fkInfo      = InpForkInfo;
   g_fkF1        = InpForkF1;
   g_fkF2        = InpForkF2;
   g_fkF3        = InpForkF3;
   g_fkLevelBars = (InpForkLevBars < 1 ? 1 : InpForkLevBars);
   g_fkFanBars   = InpForkFanBars;
   g_fkRay       = InpForkRay;
   g_fkLegWidth  = (InpForkLegW < 1 ? 1 : InpForkLegW);
   g_fkLevWidth  = (InpForkLevW < 1 ? 1 : InpForkLevW);
   g_fkEmphasis  = InpForkEmph;
   g_fkShowBox   = InpForkBox;
   g_fkShowPrice = InpForkPrice;
   g_fkBoxColor  = InpForkBoxCol;
   g_fkLevColor  = InpForkLevCol;
   g_fkAutoBars  = (InpForkAutoBars < 6 ? 6 : InpForkAutoBars);
   g_fkFont      = g_dzFont;
   g_fkFontSize  = (InpForkFontSz < 6 ? 6 : InpForkFontSz);

   //--- Alarm
   g_alOn        = InpAlarmOn;
   g_alTrigger   = InpAlarmTrig;
   g_alTimeBox   = InpAlarmTimeBox;
   g_alRepeat    = InpAlarmRepeat;
   g_alPopup     = InpAlarmPopup;
   g_alSound     = InpAlarmSound;
   g_alSoundFile = InpAlarmWav;
   g_alPush      = InpAlarmPush;
   g_alMail      = InpAlarmMail;
   g_alMark      = InpAlarmMark;
   g_alCooldown  = (InpAlarmCool < 0 ? 0 : InpAlarmCool);

   //--- Sessions
   DzSessionsReset(InpGmtOffset, InpGmtAuto);
   DzSessionAdd(InpS1Name, InpS1Span, InpS1Col, InpS1On);
   DzSessionAdd(InpS2Name, InpS2Span, InpS2Col, InpS2On);
   DzSessionAdd(InpS3Name, InpS3Span, InpS3Col, InpS3On);
   DzSessionAdd(InpS4Name, InpS4Span, InpS4Col, InpS4On);
  }

//+------------------------------------------------------------------+
//| Start                                                            |
//+------------------------------------------------------------------+
int OnInit(void)
  {
   IndicatorSetString(INDICATOR_SHORTNAME, "Dreizack");

   DzApplyInputs();

   //--- gemerkten Zustand holen, beim allerersten Start die Vorgabe
   g_dzTimerMode = InpTimerStart;
   DzStateLoad();

   DzPanelBuild();
   DzPanelRefreshTimer();

   DzAlarmReset();
   g_lastBarTime = iTime(_Symbol, _Period, 0);

   //--- ohne diese Zeile meldet MetaTrader kein Loeschen von Objekten
   ChartSetInteger(0, CHART_EVENT_OBJECT_DELETE, true);

   EventSetTimer(1);
   ChartRedraw(0);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| Ende                                                             |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();

   //--- Beim Wechsel des Zeitrahmens, beim Neuuebersetzen und beim
   //--- Aendern der Eingaben bleibt alles stehen. Nur wenn der
   //--- Indikator wirklich vom Chart genommen wird, wird aufgeraeumt.
   if(reason != REASON_REMOVE)
     {
      DzStateSave();
      return;
     }

   DzToolCancel();
   DzPanelDestroy();
   if(InpClearOnRemove)
      DzClearDrawings();
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
//| Kursbewegung                                                     |
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
   datetime t0 = iTime(_Symbol, _Period, 0);
   bool newBar = (t0 > 0 && t0 != g_lastBarTime);
   if(newBar)
      g_lastBarTime = t0;

   DzAlarmCheck(newBar);
   return rates_total;
  }

//+------------------------------------------------------------------+
//| Sekundentakt: Countdown laeuft auch ohne Ticks weiter            |
//+------------------------------------------------------------------+
void OnTimer(void)
  {
   DzPanelRefreshTimer();
   DzAlarmCheck(false);
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
//| Klicks, Ziehen, Tastatur                                         |
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   //--- Taste in der Leiste
   if(id == CHARTEVENT_OBJECT_CLICK)
     {
      //--- Ein- und Ausklappen
      if(sparam == DZ_BTN_MIN)
        {
         ObjectSetInteger(0, sparam, OBJPROP_STATE, false);
         DzToolCancel();
         g_dzMinimized = !g_dzMinimized;
         DzPanelBuild();
         DzPanelRefreshTimer();
         ChartRedraw(0);
         return;
        }

      //--- Fenster oben rechts umschalten
      if(DzPanelIsTimer(sparam))
        {
         ObjectSetInteger(0, DZ_BTN_TIMER, OBJPROP_STATE, false);
         g_dzTimerMode = (g_dzTimerMode == DZ_TM_CANDLE ? DZ_TM_SESSION : DZ_TM_CANDLE);
         DzStateSave();
         DzPanelRefreshTimer();
         ChartRedraw(0);
         return;
        }

      //--- Werkzeugtaste
      ENUM_DZ_TOOL tool;
      color        col;
      if(DzPanelButtonRole(sparam, tool, col))
        {
         if(g_dzArmedBtn == sparam)        // dieselbe Taste noch einmal: abwaehlen
            DzToolCancel();
         else
            DzToolArm(tool, col, sparam);
         ChartRedraw(0);
        }
      return;
     }

   //--- Klick ins Chart setzt die Punkte des scharfen Werkzeugs
   if(id == CHARTEVENT_CLICK)
     {
      if(g_dzTool == DZ_TOOL_NONE)
         return;

      int x = (int)lparam;
      int y = (int)dparam;
      if(DzPanelHit(x, y))
         return;                            // Klick galt der Leiste

      int      sub = 0;
      datetime t   = 0;
      double   p   = 0.0;
      if(!ChartXYToTimePrice(0, x, y, sub, t, p) || sub != 0)
         return;

      DzToolClick(t, p);
      return;
     }

   //--- ein Schenkel des Dreizacks wurde gezogen
   if(id == CHARTEVENT_OBJECT_DRAG)
     {
      long fid = DzForkIdOf(sparam);
      if(fid >= 0)
        {
         DzForkOnDrag(fid);
         ChartRedraw(0);
        }
      return;
     }

   //--- Ein Schenkel wurde geloescht: der Rest des Dreizacks geht mit.
   //--- Bewusst nur bei den Schenkeln. Alles andere am Dreizack ist
   //--- nicht auswaehlbar, kann also gar nicht vom Anwender stammen -
   //--- wohl aber vom Indikator selbst, etwa wenn die Basisbox
   //--- abgeschaltet wird. Ohne diese Einschraenkung wuerde so ein
   //--- Aufraeumen den ganzen Dreizack mitreissen.
   if(id == CHARTEVENT_OBJECT_DELETE)
     {
      string part = DzForkPartOf(sparam);
      if(part == DZ_FORK_LEG1 || part == DZ_FORK_LEG2)
        {
         long fid = DzForkIdOf(sparam);
         if(fid >= 0)
           {
            DzForkDeleteGroup(fid);
            ChartRedraw(0);
           }
        }
      return;
     }

   //--- Esc bricht das scharfe Werkzeug ab
   if(id == CHARTEVENT_KEYDOWN)
     {
      if(lparam == 27 && g_dzTool != DZ_TOOL_NONE)
        {
         DzToolCancel();
         ChartRedraw(0);
        }
      return;
     }
  }
//+------------------------------------------------------------------+
