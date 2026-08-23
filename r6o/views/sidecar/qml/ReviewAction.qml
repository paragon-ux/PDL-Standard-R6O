import QtQuick
import "."

FocusScope {
    id: control
    required property int ordinal
    required property string actionId
    required property string label
    required property color accent
    required property string uiFamily
    required property bool showKeyboardFocus
    signal activated(string actionId)
    signal keyboardNavigationStarted
    signal pointerActivated

    objectName: "reviewAction_" + actionId
    height: 31
    activeFocusOnTab: enabled

    Rectangle {
        id: badge
        objectName: "actionBadge_" + control.actionId
        width: control.width > 300 ? 30 : 28
        height: 31
        radius: DesignTokens.badgeRadius
        color: DesignTokens.controlSurface
        border.color: control.accent
        border.width: 1

        Text {
            anchors.centerIn: parent
            text: control.ordinal
            color: control.accent
            font.family: control.uiFamily
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }
    }

    Rectangle {
        id: actionBody
        objectName: "actionBody_" + control.actionId
        x: badge.width + (control.width > 300 ? 7 : 7)
        width: parent.width - x
        height: 31
        radius: DesignTokens.actionRadius
        color: DesignTokens.controlSurface
        border.color: control.showKeyboardFocus && control.activeFocus
            ? control.accent : DesignTokens.cardBorder
        border.width: 1

        Text {
            anchors.left: parent.left
            anchors.leftMargin: control.width > 300 ? 10 : 7
            anchors.verticalCenter: parent.verticalCenter
            text: control.label
            color: control.enabled ? DesignTokens.textPrimary : DesignTokens.textMuted
            font.family: control.uiFamily
            font.pixelSize: control.width > 300 ? 13 : 12
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: control.enabled
        onClicked: {
            control.pointerActivated()
            control.forceActiveFocus()
            control.activated(control.actionId)
        }
    }
    Keys.onPressed: event => {
        if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab)
            control.keyboardNavigationStarted()
    }
    Keys.onReturnPressed: if (control.enabled) control.activated(control.actionId)
    Keys.onSpacePressed: if (control.enabled) control.activated(control.actionId)
}
