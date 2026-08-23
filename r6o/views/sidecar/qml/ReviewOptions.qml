import QtQuick
import "."

Item {
    id: options
    objectName: "reviewOptions"
    required property bool expanded
    required property string uiFamily
    required property var actions
    signal actionRequested(string actionId)
    property bool keyboardFocusVisible: false

    Rectangle {
        anchors.fill: parent
        visible: !options.expanded
        radius: DesignTokens.artifactRadius
        color: DesignTokens.cardSurface
        border.color: DesignTokens.cardBorder
        border.width: 1
    }

    Text {
        objectName: "reviewOptionsTitle"
        x: options.expanded ? 11 : 13
        y: options.expanded ? 8 : 10
        text: "Review Options"
        color: DesignTokens.textPrimary
        font.family: options.uiFamily
        font.pixelSize: options.expanded ? 14 : 13
        font.weight: Font.DemiBold
    }

    Column {
        id: actionsColumn
        objectName: "actionsColumn"
        x: options.expanded ? 12 : 14
        y: options.expanded ? 42 : 36
        width: options.expanded ? options.width - 24 : options.width - 28
        spacing: options.expanded ? 10 : 5

        Repeater {
            id: actionsRepeater
            model: options.actions
            ReviewAction {
                required property var modelData
                width: actionsColumn.width
                ordinal: Number(modelData.ordinal)
                actionId: String(modelData.action_id)
                label: String(modelData.label)
                enabled: Boolean(modelData.enabled)
                uiFamily: options.uiFamily
                showKeyboardFocus: options.keyboardFocusVisible
                accent: ordinal === 1 ? DesignTokens.active
                    : ordinal === 2 ? DesignTokens.actionBlue
                    : ordinal === 3 ? DesignTokens.actionAmber
                    : DesignTokens.actionNeutral
                onActivated: actionId => options.actionRequested(actionId)
                onKeyboardNavigationStarted: options.keyboardFocusVisible = true
                onPointerActivated: options.keyboardFocusVisible = false
            }
        }
    }

    Text {
        objectName: "tipText"
        x: options.expanded ? 11 : 13
        y: options.expanded ? 234 : 207
        width: options.width - 24
        text: "<b>Tip:</b> Type directly in the chat below<br>to provide other feedback."
        textFormat: Text.RichText
        color: DesignTokens.textMuted
        font.family: options.uiFamily
        font.pixelSize: options.expanded ? 12 : 11
        lineHeight: 1.5
    }

    function focusFirstAction() {
        keyboardFocusVisible = false
        const first = actionsRepeater.itemAt(0)
        if (first) first.forceActiveFocus()
    }
}
