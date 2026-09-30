//+------------------------------------------------------------------+
//|                                                      DzTypes.mqh |
//|              BauBox Dreizack - Namen, Aufzaehlungen, Bausteine   |
//+------------------------------------------------------------------+
#ifndef BAUBOX_DZ_TYPES_MQH
#define BAUBOX_DZ_TYPES_MQH

//+------------------------------------------------------------------+
//| Namensraum                                                       |
//|                                                                  |
//| Jedes Objekt, das dieser Indikator anlegt, traegt eines dieser   |
//| Praefixe. Daran haengt die gesamte Logik: das Panel raeumt nur   |
//| seine eigenen Teile ab, und der Alarm sieht ausschliesslich      |
//| Objekte mit DZ_PRE_ALARM an. Ein von Hand gezogenes Rechteck     |
//| von MetaTrader heisst "Rectangle 1234" und faellt damit nie in   |
//| die Alarmpruefung - genau das war die Anforderung.               |
//+------------------------------------------------------------------+
#define DZ_PRE_PANEL    "DZ_P_"     // Panelteile (Hintergrund, Tasten, Texte)
#define DZ_PRE_RECT     "DZ_R_"     // Rechteck ohne Alarm
#define DZ_PRE_ALARM    "DZ_A_"     // Rechteck mit Alarm
#define DZ_PRE_LINE     "DZ_L_"     // Trendlinie
#define DZ_PRE_FORK     "DZ_T_"     // Dreizack

//--- Namensteile eines Dreizacks: DZ_T_<lfd>_<teil>
//--- Die drei Anker stecken in den beiden Schenkeln: G1 laeuft von A
//--- nach B, G2 von B nach C. Nur diese beiden sind auswaehlbar, sie
//--- dienen zugleich als Griffe zum Nachjustieren.
#define DZ_FORK_LEG1    "G1"        // Schenkel A nach B  (Impuls)
#define DZ_FORK_LEG2    "G2"        // Schenkel B nach C  (Ruecklauf)
#define DZ_FORK_PRONG   "Z"         // Zinke zur jeweiligen Stufe  (Z1 Z2 Z3)
#define DZ_FORK_LEVEL   "S"         // waagerechte Stufe           (S1 S2 S3)
#define DZ_FORK_TAG     "N"         // Beschriftung der Stufe      (N1 N2 N3)
#define DZ_FORK_BOX     "BX"        // gestrichelte Basisbox
#define DZ_FORK_INFO    "IN"        // Messtext am Impuls
#define DZ_FORK_META    "MT"        // unsichtbarer Merkzettel der Anker

//--- Tasten des Panels
#define DZ_BTN_MIN      DZ_PRE_PANEL "MIN"     // Minimieren bzw. Wiederherstellen
#define DZ_BTN_TIMER    DZ_PRE_PANEL "TMR"     // Fenster oben rechts, schaltet um
#define DZ_LBL_TIMER1   DZ_PRE_PANEL "TMR1"    // Kopfzeile im Fenster
#define DZ_LBL_TIMER2   DZ_PRE_PANEL "TMR2"    // Wertzeile im Fenster
#define DZ_LBL_HINT     DZ_PRE_PANEL "HINT"    // Zeile mit der naechsten Klickanweisung
#define DZ_LBL_TITLE    DZ_PRE_PANEL "TTL"     // Name im eingeklappten Zustand
#define DZ_BG_MAIN      DZ_PRE_PANEL "BG"      // Hintergrundflaeche
#define DZ_STATE_OBJ    DZ_PRE_PANEL "STATE"   // unsichtbarer Merker fuer den Zustand

//--- Anzahl der Tasten je Gruppe, entspricht der Vorlage
#define DZ_N_ALARM      6
#define DZ_N_RECT       4
#define DZ_N_FORK       4
#define DZ_N_LINE       4

//+------------------------------------------------------------------+
//| Welches Werkzeug wartet gerade auf Klicks im Chart               |
//+------------------------------------------------------------------+
enum ENUM_DZ_TOOL
  {
   DZ_TOOL_NONE = 0,       // nichts scharf
   DZ_TOOL_RECT,           // Rechteck ohne Alarm
   DZ_TOOL_ALARM,          // Rechteck mit Alarm
   DZ_TOOL_FORK,           // Dreizack
   DZ_TOOL_LINE            // Trendlinie
  };

//+------------------------------------------------------------------+
//| Wie der Dreizack gesetzt wird                                    |
//+------------------------------------------------------------------+
enum ENUM_DZ_FORKMODE
  {
   DZ_FORK_3CLICK = 0,     // drei Klicks: Start, Spitze, Ruecklauf
   DZ_FORK_1CLICK          // ein Klick, Schwung wird gesucht
  };

//+------------------------------------------------------------------+
//| Von wo aus die Stufen gemessen werden                            |
//+------------------------------------------------------------------+
enum ENUM_DZ_BASE
  {
   DZ_BASE_C = 0,          // vom Ruecklauf aus (uebliche Messbewegung)
   DZ_BASE_B               // von der Spitze aus
  };

//+------------------------------------------------------------------+
//| Was der kleine Messtext am Dreizack zeigt                        |
//+------------------------------------------------------------------+
enum ENUM_DZ_INFO
  {
   DZ_INFO_OFF = 0,        // nichts
   DZ_INFO_BARS_POINTS,    // Kerzen des Impulses / Punkte      z. B. 9/98
   DZ_INFO_POINTS,         // nur Punkte des Impulses
   DZ_INFO_TARGET          // Punkte des Impulses / Weg bis Stufe 3
  };

//+------------------------------------------------------------------+
//| Wann ein Alarmrechteck ausloest                                  |
//+------------------------------------------------------------------+
enum ENUM_DZ_TRIGGER
  {
   DZ_TRIG_TOUCH = 0,      // sobald der Kurs die Zone beruehrt
   DZ_TRIG_CLOSE           // erst wenn eine Kerze darin schliesst
  };

//+------------------------------------------------------------------+
//| Anzeige im Fenster oben rechts                                   |
//+------------------------------------------------------------------+
enum ENUM_DZ_TIMERMODE
  {
   DZ_TM_CANDLE = 0,       // Restzeit der laufenden Kerze
   DZ_TM_SESSION           // laufende Handelssession samt Zeitspanne
  };

//+------------------------------------------------------------------+
//| Ecke, an der das Panel klebt                                     |
//+------------------------------------------------------------------+
enum ENUM_DZ_CORNER
  {
   DZ_CORNER_RU = 0,       // oben rechts
   DZ_CORNER_LU,           // oben links
   DZ_CORNER_RL,           // unten rechts
   DZ_CORNER_LL            // unten links
  };

//+------------------------------------------------------------------+
//| Die drei Anker eines Dreizacks                                   |
//+------------------------------------------------------------------+
struct DzAnchors
  {
   datetime          ta, tb, tc;
   double            pa, pb, pc;
   bool              ok;
  };

//+------------------------------------------------------------------+
//| Eine Handelssession, Zeiten bereits in Serverzeit                |
//+------------------------------------------------------------------+
struct DzSessionDef
  {
   string            name;
   int               from;      // Minuten seit Mitternacht
   int               to;        // Minuten seit Mitternacht
   color             col;
   bool              use;
  };

#endif // BAUBOX_DZ_TYPES_MQH
//+------------------------------------------------------------------+
