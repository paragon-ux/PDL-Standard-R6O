pragma Singleton
import QtQuick

QtObject {
    readonly property color outerBorder: "#22282F"
    readonly property color cardBorder: "#242A30"
    readonly property color outerSurface: "#12181E"
    readonly property color expandedSurface: "#10171D"
    readonly property color cardSurface: "#11171D"
    readonly property color controlSurface: "#0D141A"
    readonly property color artifactBody: "#0B1117"
    readonly property color textPrimary: "#EEF2F5"
    readonly property color textMuted: "#A8AFB6"
    readonly property color artifactText: "#CBD1D5"
    readonly property color artifactAccent: "#A891E9"
    readonly property color stageFill: "#2A2145"
    readonly property color stageBorder: "#40325F"
    readonly property color active: "#4BD477"
    readonly property color actionBlue: "#48A7E8"
    readonly property color actionAmber: "#E58B25"
    readonly property color actionNeutral: "#9AA4AD"

    readonly property int outerRadius: 12
    readonly property int artifactRadius: 9
    readonly property int artifactBodyRadius: 6
    readonly property int controlRadius: 6
    readonly property int actionRadius: 5
    readonly property int badgeRadius: 5
    readonly property int stageRadius: 4
}
