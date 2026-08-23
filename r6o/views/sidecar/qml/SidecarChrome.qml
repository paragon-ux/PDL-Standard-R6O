import QtQuick
import "."

Item {
    id: chrome
    objectName: "sidecarChrome"
    required property bool expanded
    required property string uiFamily
    required property string stageLabel
    required property string statusLabel
    signal expandRequested
    signal closeRequested

    Text {
        id: title
        objectName: "sidecarTitle"
        x: 18
        y: 13
        text: "PDLt Review"
        color: DesignTokens.textPrimary
        font.family: chrome.uiFamily
        font.pixelSize: 16
        font.weight: Font.Bold
    }

    Rectangle {
        id: stageBadge
        objectName: "stageBadge"
        x: chrome.expanded ? 132 : 135
        y: 16
        width: 98
        height: 18
        radius: DesignTokens.stageRadius
        color: DesignTokens.stageFill
        border.color: DesignTokens.stageBorder
        border.width: 1

        Text {
            anchors.centerIn: parent
            text: chrome.stageLabel
            color: DesignTokens.stageText
            font.family: chrome.uiFamily
            font.pixelSize: 9
            font.weight: Font.DemiBold
        }
    }

    Rectangle {
        id: statusDot
        objectName: "activeDot"
        x: chrome.expanded ? 245 : 506
        y: 20
        width: 7
        height: 7
        radius: 4
        color: DesignTokens.active
    }

    Text {
        objectName: "activeLabel"
        x: statusDot.x + 13
        y: 16
        text: chrome.statusLabel
        color: DesignTokens.active
        font.family: chrome.uiFamily
        font.pixelSize: 11
        font.weight: Font.DemiBold
    }

    Rectangle {
        id: expandControl
        objectName: "expandControl"
        visible: !chrome.expanded
        x: 587
        y: 8
        width: 32
        height: 30
        radius: DesignTokens.controlRadius
        color: DesignTokens.controlSurface
        border.color: DesignTokens.cardBorder
        border.width: 1
        activeFocusOnTab: visible

        Image {
            objectName: "expandIcon"
            anchors.centerIn: parent
            source: "../assets/icons/expand.svg"
            sourceSize.width: 17
            sourceSize.height: 15
            width: 17
            height: 15
            fillMode: Image.PreserveAspectFit
        }
        MouseArea { anchors.fill: parent; onClicked: chrome.expandRequested() }
        Keys.onReturnPressed: chrome.expandRequested()
        Keys.onSpacePressed: chrome.expandRequested()
    }

    Rectangle {
        id: closeControl
        objectName: "closeControl"
        x: chrome.expanded ? 371 : 629
        y: 8
        width: 32
        height: 30
        radius: DesignTokens.controlRadius
        color: DesignTokens.controlSurface
        border.color: DesignTokens.cardBorder
        border.width: 1
        activeFocusOnTab: true

        Image {
            objectName: "closeIcon"
            anchors.centerIn: parent
            source: "../assets/icons/close.svg"
            sourceSize.width: 14
            sourceSize.height: 14
            width: 14
            height: 14
            fillMode: Image.PreserveAspectFit
        }
        MouseArea { anchors.fill: parent; onClicked: chrome.closeRequested() }
        Keys.onReturnPressed: chrome.closeRequested()
        Keys.onSpacePressed: chrome.closeRequested()
    }
}
