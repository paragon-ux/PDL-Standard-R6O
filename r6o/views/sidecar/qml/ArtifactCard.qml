import QtQuick
import "."

Rectangle {
    id: card
    objectName: "artifactCard"
    required property bool expanded
    required property string uiFamily
    required property string monoFamily
    required property var artifactLines
    required property string artifactTitle
    required property string sourceLabel
    required property string sourceValue
    required property bool canOpenExternal
    required property bool canCopy
    signal openRequested
    signal copyRequested

    radius: DesignTokens.artifactRadius
    color: DesignTokens.cardSurface
    border.color: DesignTokens.cardBorder
    border.width: 1

    Text {
        objectName: "artifactTitle"
        x: 11
        y: card.expanded ? 15 : 11
        text: card.artifactTitle
        color: DesignTokens.textPrimary
        font.family: card.uiFamily
        font.pixelSize: card.expanded ? 14 : 13
        font.weight: Font.DemiBold
    }

    Rectangle {
        id: openControl
        objectName: "openEditorControl"
        visible: card.canOpenExternal
        x: card.width - 123
        y: card.expanded ? 8 : 7
        width: 112
        height: 28
        radius: DesignTokens.controlRadius
        color: DesignTokens.controlSurface
        border.color: DesignTokens.cardBorder
        activeFocusOnTab: true

        Text {
            x: 9
            anchors.verticalCenter: parent.verticalCenter
            text: "Open in Editor"
            color: DesignTokens.textPrimary
            font.family: card.uiFamily
            font.pixelSize: 12
        }
        Image {
            objectName: "externalLinkIcon"
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            source: "../assets/icons/external-link.svg"
            sourceSize.width: 12
            sourceSize.height: 12
            width: 12
            height: 12
        }
        MouseArea { anchors.fill: parent; onClicked: card.openRequested() }
        Keys.onReturnPressed: card.openRequested()
        Keys.onSpacePressed: card.openRequested()
    }

    Rectangle {
        id: body
        objectName: "artifactBody"
        x: 11
        y: card.expanded ? 43 : 38
        width: card.width - 22
        height: card.expanded ? 248 : 167
        radius: DesignTokens.artifactBodyRadius
        color: DesignTokens.artifactBody
        border.color: DesignTokens.cardBorder
        border.width: 1
        clip: true

        Flickable {
            id: artifactFlickable
            objectName: "artifactFlickable"
            anchors.fill: parent
            anchors.margins: 10
            contentWidth: width
            contentHeight: artifactLinesColumn.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            interactive: contentHeight > height

            Column {
                id: artifactLinesColumn
                width: artifactFlickable.width
                spacing: card.expanded ? 2 : 0
                Repeater {
                    model: card.artifactLines
                    Text {
                        required property string modelData
                        width: artifactLinesColumn.width
                        height: card.expanded ? 22 : 16
                        text: modelData.length === 0 ? " " : modelData
                        color: modelData === "# Prompt" ? DesignTokens.artifactAccent : DesignTokens.artifactText
                        font.family: card.monoFamily
                        font.pixelSize: card.expanded ? 13 : 11
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }

    Text {
        id: sourceLabel
        objectName: "sourceLabel"
        x: card.expanded ? 18 : 13
        y: card.expanded ? 308 : 216
        text: card.sourceLabel
        color: DesignTokens.textMuted
        font.family: card.uiFamily
        font.pixelSize: 11
    }
    Text {
        objectName: "sourceValue"
        x: card.expanded ? 18 : sourceLabel.x + sourceLabel.width + 7
        y: card.expanded ? 326 : 216
        text: card.sourceValue
        color: DesignTokens.textMuted
        font.family: card.uiFamily
        font.pixelSize: 11
    }

    Rectangle {
        id: copyControl
        objectName: "copyControl"
        visible: card.canCopy
        x: card.width - 68
        y: card.expanded ? 303 : 215
        width: 56
        height: 30
        radius: DesignTokens.controlRadius
        color: DesignTokens.controlSurface
        border.color: DesignTokens.cardBorder
        activeFocusOnTab: true

        Text {
            anchors.centerIn: parent
            text: "Copy"
            color: DesignTokens.textPrimary
            font.family: card.uiFamily
            font.pixelSize: 12
        }
        MouseArea { anchors.fill: parent; onClicked: card.copyRequested() }
        Keys.onReturnPressed: card.copyRequested()
        Keys.onSpacePressed: card.copyRequested()
    }

    function scrollToBottom() {
        artifactFlickable.contentY = Math.max(0, artifactFlickable.contentHeight - artifactFlickable.height)
    }
}
