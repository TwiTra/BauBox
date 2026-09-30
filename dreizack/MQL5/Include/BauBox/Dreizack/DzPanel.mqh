//+------------------------------------------------------------------+
//|                                                      DzPanel.mqh |
//|                   BauBox Dreizack - Bedienleiste am Chartrand    |
//|                                                                  |
//| Aufbau von links nach rechts, so wie in der Vorlage:             |
//|                                                                  |
//|   [ 3x2 Rechtecke mit Alarm ][ 2x2 Rechtecke ][ 2x2 Dreizack ]   |
//|                                        [ Kerzenzeit / Session ]  |
//|                                        [ 4x Trendlinie      ][-] |
//|                                                                  |
//| Rechts oben sitzt das Fenster mit der Kerzenrestzeit, darunter   |
//| die Trendlinientasten, ganz aussen die Taste zum Einklappen.     |
//+------------------------------------------------------------------+
#ifndef BAUBOX_DZ_PANEL_MQH
#define BAUBOX_DZ_PANEL_MQH

#include "DzTypes.mqh"
#include "DzUtil.mqh"
#include "DzSession.mqh"

//--- Tastennamen
#define DZ_BTN_ALARM    DZ_PRE_PANEL "BA"
#define DZ_BTN_RECT     DZ_PRE_PANEL "BR"
#define DZ_BTN_FORK     DZ_PRE_PANEL "BF"
#define DZ_BTN_LINE     DZ_PRE_PANEL "BL"

//--- Einstellungen, die das Hauptprogramm hereinreicht
int    g_dzCorner      = (int)CORNER_RIGHT_UPPER;
int    g_dzMarginX     = 8;
int    g_dzMarginY     = 18;
int    g_dzScale       = 100;
string g_dzFont        = "Arial";
color  g_dzPanelBg     = C'238,238,238';
color  g_dzPanelEdge   = C'150,150,150';
color  g_dzPanelInk    = C'40,40,40';
color  g_dzTimerBg     = C'68,114,196';
color  g_dzTimerInk    = C'255,255,255';
bool   g_dzMiniKeepTmr = true;

color  g_dzColAlarm[DZ_N_ALARM];
color  g_dzColRect[DZ_N_RECT];
color  g_dzColFork[DZ_N_FORK];
color  g_dzColLine[DZ_N_LINE];

//--- Zustand
bool             g_dzMinimized = false;
ENUM_DZ_TIMERMODE g_dzTimerMode = DZ_TM_CANDLE;
string           g_dzArmedBtn  = "";      // Name der gedrueckten Taste

//--- Masse, werden in DzGeoCalc gefuellt
int g_gBtn, g_gGap, g_gSep, g_gPad, g_gMinB;
int g_gTmW, g_gTmH, g_gTitleW;
int g_gXA, g_gXB, g_gXC, g_gXD, g_gXMin;
int g_gY1, g_gY2, g_gYTm, g_gYTl;
int g_gFullW, g_gFullH, g_gMiniW, g_gMiniH;
int g_gCurW, g_gCurH;                      // gilt fuer den gerade gezeigten Zustand

//--- Schriftgroessen
int g_gFsBtn, g_gFsHead, g_gFsBig, g_gFsHint;

//+------------------------------------------------------------------+
//| Wert mit dem Panelmassstab skalieren                             |
//+------------------------------------------------------------------+
int DzS(const int v)
  {
   int r = (int)MathRound((double)v * (double)g_dzScale / 100.0);
   return (r < 1 ? 1 : r);
  }

//--- hilft beim Lesen der Eckenabfragen
bool DzCornerIsRight(void)
  {
   return (g_dzCorner == (int)CORNER_RIGHT_UPPER || g_dzCorner == (int)CORNER_RIGHT_LOWER);
  }
bool DzCornerIsLower(void)
  {
   return (g_dzCorner == (int)CORNER_LEFT_LOWER || g_dzCorner == (int)CORNER_RIGHT_LOWER);
  }

//+------------------------------------------------------------------+
//| Umrechnung der panelinternen Koordinaten auf die Abstaende, die  |
//| MetaTrader erwartet. Intern wird immer von links oben gezaehlt,  |
//| unabhaengig davon, an welcher Ecke das Panel klebt.              |
//|                                                                  |
//| Fuer Textfelder ohne Groesse wird w bzw. h als 0 uebergeben; der |
//| uebergebene Ort ist dann genau der Ankerpunkt.                   |
//+------------------------------------------------------------------+
int DzPx(const int localX, const int w)
  {
   if(DzCornerIsRight())
      return g_dzMarginX + (g_gCurW - localX - w);
   return g_dzMarginX + localX;
  }
int DzPy(const int localY, const int h)
  {
   if(DzCornerIsLower())
      return g_dzMarginY + (g_gCurH - localY - h);
   return g_dzMarginY + localY;
  }

//--- passender Ankerpunkt fuer Texte am linken bzw. rechten Rand
ENUM_ANCHOR_POINT DzAnchorSide(void)
  {
   return (DzCornerIsRight() ? ANCHOR_RIGHT_UPPER : ANCHOR_LEFT_UPPER);
  }

//+------------------------------------------------------------------+
//| Alle Masse aus dem Massstab ableiten                             |
//+------------------------------------------------------------------+
void DzGeoCalc(void)
  {
   g_gBtn  = DzS(22);
   g_gGap  = DzS(3);
   g_gSep  = DzS(9);
   g_gPad  = DzS(6);
   g_gMinB = DzS(18);

   int wA     = 3 * g_gBtn + 2 * g_gGap;      // Rechtecke mit Alarm
   int wB     = 2 * g_gBtn + g_gGap;          // Rechtecke ohne Alarm
   int wC     = wB;                           // Dreizack
   int wLines = 4 * g_gBtn + 3 * g_gGap;      // Trendlinien

   g_gTmW    = (int)MathMax(DzS(132), wLines);
   g_gTmH    = DzS(25);
   g_gTitleW = DzS(74);

   int hRows = 2 * g_gBtn + g_gGap;           // zwei Tastenreihen
   int hRight = g_gTmH + g_gGap + g_gBtn;     // Fenster plus Trendlinienreihe
   int hCont = (int)MathMax(hRows, hRight);

   g_gXA   = g_gPad;
   g_gXB   = g_gXA + wA + g_gSep;
   g_gXC   = g_gXB + wB + g_gSep;
   g_gXD   = g_gXC + wC + g_gSep;
   g_gXMin = g_gXD + g_gTmW + g_gPad;

   g_gFullW = g_gXMin + g_gMinB + g_gPad;
   g_gFullH = g_gPad + hCont + g_gPad;

   g_gY1  = g_gPad + (hCont - hRows) / 2;
   g_gY2  = g_gY1 + g_gBtn + g_gGap;
   g_gYTm = g_gPad;
   g_gYTl = g_gYTm + g_gTmH + g_gGap;

   if(g_dzMiniKeepTmr)
     {
      g_gMiniW = g_gPad + g_gTmW + g_gPad + g_gMinB + g_gPad;
      g_gMiniH = g_gPad + g_gTmH + g_gPad;
     }
   else
     {
      g_gMiniW = g_gPad + g_gTitleW + g_gPad + g_gMinB + g_gPad;
      g_gMiniH = g_gPad + g_gMinB + g_gPad;
     }

   g_gFsBtn  = (int)MathMax(6, DzS(8));
   g_gFsHead = (int)MathMax(6, DzS(8));
   g_gFsBig  = (int)MathMax(7, DzS(11));
   g_gFsHint = (int)MathMax(6, DzS(9));
  }

//+------------------------------------------------------------------+
//| Zustand merken. Er haengt an einem Objekt, das auf keinem        |
//| Zeitrahmen gezeichnet wird - so ueberlebt er Zeitrahmenwechsel   |
//| und das Neuuebersetzen, ohne im Chart sichtbar zu sein.          |
//+------------------------------------------------------------------+
void DzStateSave(void)
  {
   if(ObjectFind(0, DZ_STATE_OBJ) < 0)
     {
      ObjectCreate(0, DZ_STATE_OBJ, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, DZ_STATE_OBJ, OBJPROP_TIMEFRAMES, OBJ_NO_PERIODS);
      ObjectSetInteger(0, DZ_STATE_OBJ, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, DZ_STATE_OBJ, OBJPROP_HIDDEN,     true);
     }
   ObjectSetString(0, DZ_STATE_OBJ, OBJPROP_TEXT,
                   StringFormat("m=%d;t=%d", (g_dzMinimized ? 1 : 0), (int)g_dzTimerMode));
  }

void DzStateLoad(void)
  {
   if(ObjectFind(0, DZ_STATE_OBJ) < 0)
      return;
   string s = ObjectGetString(0, DZ_STATE_OBJ, OBJPROP_TEXT);
   string part[];
   int n = StringSplit(s, ';', part);
   for(int i = 0; i < n; i++)
     {
      if(StringSubstr(part[i], 0, 2) == "m=")
         g_dzMinimized = (StringToInteger(StringSubstr(part[i], 2)) != 0);
      if(StringSubstr(part[i], 0, 2) == "t=")
         g_dzTimerMode = (ENUM_DZ_TIMERMODE)StringToInteger(StringSubstr(part[i], 2));
     }
  }

//+------------------------------------------------------------------+
//| Eine Farbtaste setzen                                            |
//+------------------------------------------------------------------+
void DzColorButton(const string name, const int lx, const int ly,
                   const color swatch, const string tip)
  {
   color edge = DzMix(swatch, clrBlack, 0.35);
   DzButton(name, g_dzCorner, DzPx(lx, g_gBtn), DzPy(ly, g_gBtn),
            g_gBtn, g_gBtn, swatch, edge, "", g_dzFont, g_gFsBtn, DzInk(swatch), tip);
  }

//+------------------------------------------------------------------+
//| Leiste aufbauen oder auffrischen                                 |
//+------------------------------------------------------------------+
void DzPanelBuild(void)
  {
   DzGeoCalc();
   g_gCurW = (g_dzMinimized ? g_gMiniW : g_gFullW);
   g_gCurH = (g_dzMinimized ? g_gMiniH : g_gFullH);

   //--- Hintergrund
   DzPane(DZ_BG_MAIN, g_dzCorner, DzPx(0, g_gCurW), DzPy(0, g_gCurH),
          g_gCurW, g_gCurH, g_dzPanelBg, g_dzPanelEdge);

   //--- Taste zum Ein- und Ausklappen, immer rechts oben im Panel
   int mx = (g_dzMinimized ? g_gCurW - g_gPad - g_gMinB : g_gXMin);
   DzButton(DZ_BTN_MIN, g_dzCorner, DzPx(mx, g_gMinB), DzPy(g_gPad, g_gMinB),
            g_gMinB, g_gMinB, DzMix(g_dzPanelBg, clrBlack, 0.10), g_dzPanelEdge,
            (g_dzMinimized ? "+" : "-"), g_dzFont, (int)MathMax(7, DzS(9)), g_dzPanelInk,
            (g_dzMinimized ? "Leiste ausklappen" : "Leiste einklappen"));

   //--- Werkzeugtasten nur im ausgeklappten Zustand
   if(!g_dzMinimized)
     {
      for(int i = 0; i < DZ_N_ALARM; i++)                 // 3 Spalten, 2 Reihen
        {
         int col = i % 3, row = i / 3;
         DzColorButton(DZ_BTN_ALARM + IntegerToString(i),
                       g_gXA + col * (g_gBtn + g_gGap),
                       (row == 0 ? g_gY1 : g_gY2),
                       g_dzColAlarm[i],
                       StringFormat("Rechteck MIT Alarm %d\nzwei Klicks im Chart", i + 1));
        }

      for(int i = 0; i < DZ_N_RECT; i++)                  // 2 Spalten, 2 Reihen
        {
         int col = i % 2, row = i / 2;
         DzColorButton(DZ_BTN_RECT + IntegerToString(i),
                       g_gXB + col * (g_gBtn + g_gGap),
                       (row == 0 ? g_gY1 : g_gY2),
                       g_dzColRect[i],
                       StringFormat("Rechteck ohne Alarm %d\nzwei Klicks im Chart", i + 1));
        }

      for(int i = 0; i < DZ_N_FORK; i++)                  // 2 Spalten, 2 Reihen
        {
         int col = i % 2, row = i / 2;
         DzColorButton(DZ_BTN_FORK + IntegerToString(i),
                       g_gXC + col * (g_gBtn + g_gGap),
                       (row == 0 ? g_gY1 : g_gY2),
                       g_dzColFork[i],
                       StringFormat("Dreizack %d\nStart, Spitze, Ruecklauf", i + 1));
        }

      for(int i = 0; i < DZ_N_LINE; i++)                  // eine Reihe unter dem Fenster
        {
         DzColorButton(DZ_BTN_LINE + IntegerToString(i),
                       g_gXD + i * (g_gBtn + g_gGap), g_gYTl,
                       g_dzColLine[i],
                       StringFormat("Trendlinie %d\nzwei Klicks im Chart", i + 1));
        }
     }
   else
     {
      DzDeletePrefix(DZ_BTN_ALARM);
      DzDeletePrefix(DZ_BTN_RECT);
      DzDeletePrefix(DZ_BTN_FORK);
      DzDeletePrefix(DZ_BTN_LINE);
     }

   //--- Fenster oben rechts
   bool showTimer = (!g_dzMinimized || g_dzMiniKeepTmr);
   if(showTimer)
     {
      int tx = (g_dzMinimized ? g_gPad : g_gXD);
      DzButton(DZ_BTN_TIMER, g_dzCorner, DzPx(tx, g_gTmW), DzPy(g_gYTm, g_gTmH),
               g_gTmW, g_gTmH, g_dzTimerBg, DzMix(g_dzTimerBg, clrBlack, 0.35),
               "", g_dzFont, g_gFsHead, g_dzTimerInk,
               "Klick schaltet zwischen Kerzenzeit und Handelssession um");

      //--- zwei Textzeilen darueber, am linken Rand des Fensters
      int inx = tx + DzS(6);
      DzLabel(DZ_LBL_TIMER1, g_dzCorner, DzPx(inx, 0), DzPy(g_gYTm + DzS(2), 0),
              "", g_dzTimerInk, g_dzFont, g_gFsHead, ANCHOR_LEFT_UPPER);
      DzLabel(DZ_LBL_TIMER2, g_dzCorner, DzPx(inx, 0), DzPy(g_gYTm + DzS(10), 0),
              "", g_dzTimerInk, g_dzFont, g_gFsBig, ANCHOR_LEFT_UPPER);
     }
   else
     {
      DzDelete(DZ_BTN_TIMER);
      DzDelete(DZ_LBL_TIMER1);
      DzDelete(DZ_LBL_TIMER2);
     }

   //--- Name, wenn das Fenster im eingeklappten Zustand ausgeblendet ist
   if(g_dzMinimized && !g_dzMiniKeepTmr)
      DzLabel(DZ_LBL_TITLE, g_dzCorner, DzPx(g_gPad, 0), DzPy(g_gPad + DzS(4), 0),
              "Dreizack", g_dzPanelInk, g_dzFont, g_gFsHead, ANCHOR_LEFT_UPPER);
   else
      DzDelete(DZ_LBL_TITLE);

   //--- Hinweiszeile ausserhalb der Leiste
   int hintLocalX = (DzCornerIsRight() ? g_gCurW - g_gPad : g_gPad);
   int hintLocalY = (DzCornerIsLower() ? -DzS(4) : g_gCurH + DzS(4));
   DzLabel(DZ_LBL_HINT, g_dzCorner, DzPx(hintLocalX, 0), DzPy(hintLocalY, 0),
           "", g_dzPanelInk, g_dzFont, g_gFsHint, DzAnchorSide());

   DzStateSave();
  }

//+------------------------------------------------------------------+
//| Leiste komplett entfernen                                        |
//+------------------------------------------------------------------+
void DzPanelDestroy(void)
  {
   DzDeletePrefix(DZ_PRE_PANEL);   // der Merker gehoert dazu und geht mit
  }

//+------------------------------------------------------------------+
//| Liegt der Punkt auf der Leiste? Klicks dort setzen keine Punkte. |
//+------------------------------------------------------------------+
bool DzPanelHit(const int x, const int y)
  {
   int cw = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   int ch = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS);

   int left, top;
   if(DzCornerIsRight())
      left = cw - g_dzMarginX - g_gCurW;
   else
      left = g_dzMarginX;

   if(DzCornerIsLower())
      top = ch - g_dzMarginY - g_gCurH;
   else
      top = g_dzMarginY;

   //--- etwas Luft, damit ein Klick knapp daneben nichts ausloest
   int pad = DzS(3);
   return (x >= left - pad && x <= left + g_gCurW + pad &&
           y >= top  - pad && y <= top  + g_gCurH + pad);
  }

//+------------------------------------------------------------------+
//| Inhalt des Fensters oben rechts auffrischen                      |
//+------------------------------------------------------------------+
void DzPanelRefreshTimer(void)
  {
   if(ObjectFind(0, DZ_LBL_TIMER1) < 0)
      return;

   string head, sub;
   color  ink = g_dzTimerInk;

   if(g_dzTimerMode == DZ_TM_CANDLE)
     {
      head = DzPeriodName(_Period) + "  Kerze";
      sub  = DzClock(DzCandleLeft());
     }
   else
     {
      color sc;
      DzSessionState(DzServerNow(), head, sub, sc);
     }

   ObjectSetString(0, DZ_LBL_TIMER1, OBJPROP_TEXT, head);
   ObjectSetString(0, DZ_LBL_TIMER2, OBJPROP_TEXT, sub);
   ObjectSetInteger(0, DZ_LBL_TIMER1, OBJPROP_COLOR, DzMix(ink, g_dzTimerBg, 0.30));
   ObjectSetInteger(0, DZ_LBL_TIMER2, OBJPROP_COLOR, ink);
  }

//+------------------------------------------------------------------+
//| Hinweiszeile setzen                                              |
//+------------------------------------------------------------------+
void DzPanelHint(const string text)
  {
   if(ObjectFind(0, DZ_LBL_HINT) >= 0)
      ObjectSetString(0, DZ_LBL_HINT, OBJPROP_TEXT, text);
  }

//+------------------------------------------------------------------+
//| Gedrueckte Taste anzeigen. MetaTrader laesst eine Taste nach dem |
//| Klick gedrueckt stehen; genau das nutzen wir als Statusanzeige.  |
//+------------------------------------------------------------------+
void DzPanelArm(const string name)
  {
   if(g_dzArmedBtn != "" && ObjectFind(0, g_dzArmedBtn) >= 0)
      ObjectSetInteger(0, g_dzArmedBtn, OBJPROP_STATE, false);

   g_dzArmedBtn = name;

   if(name != "" && ObjectFind(0, name) >= 0)
      ObjectSetInteger(0, name, OBJPROP_STATE, true);
  }

//+------------------------------------------------------------------+
//| Gehoert der Name zu einer Werkzeugtaste? Dann Werkzeug und Farbe |
//+------------------------------------------------------------------+
bool DzPanelButtonRole(const string name, ENUM_DZ_TOOL &tool, color &col)
  {
   tool = DZ_TOOL_NONE;
   col  = clrNONE;

   string groups[4];
   groups[0] = DZ_BTN_ALARM;
   groups[1] = DZ_BTN_RECT;
   groups[2] = DZ_BTN_FORK;
   groups[3] = DZ_BTN_LINE;

   for(int g = 0; g < 4; g++)
     {
      int len = StringLen(groups[g]);
      if(StringSubstr(name, 0, len) != groups[g])
         continue;

      int idx = (int)StringToInteger(StringSubstr(name, len));
      switch(g)
        {
         case 0:
            if(idx < 0 || idx >= DZ_N_ALARM) return false;
            tool = DZ_TOOL_ALARM; col = g_dzColAlarm[idx]; return true;
         case 1:
            if(idx < 0 || idx >= DZ_N_RECT)  return false;
            tool = DZ_TOOL_RECT;  col = g_dzColRect[idx];  return true;
         case 2:
            if(idx < 0 || idx >= DZ_N_FORK)  return false;
            tool = DZ_TOOL_FORK;  col = g_dzColFork[idx];  return true;
         case 3:
            if(idx < 0 || idx >= DZ_N_LINE)  return false;
            tool = DZ_TOOL_LINE;  col = g_dzColLine[idx];  return true;
        }
     }
   return false;
  }

//--- Gehoert der Name zum Fenster oben rechts?
bool DzPanelIsTimer(const string name)
  {
   return (name == DZ_BTN_TIMER || name == DZ_LBL_TIMER1 || name == DZ_LBL_TIMER2);
  }

#endif // BAUBOX_DZ_PANEL_MQH
//+------------------------------------------------------------------+
