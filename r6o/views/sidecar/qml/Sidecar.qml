import QtQuick
import QtQuick.Window
import "."

Window {
    id: root
    objectName: "sidecarWindow"
    width: sidecarBridge.mode === "EXPANDED" ? 412 : 675
    height: sidecarBridge.mode === "EXPANDED" ? 806 : 300
    minimumWidth: sidecarBridge.mode === "EXPANDED" ? 412 : 675
    maximumWidth: sidecarBridge.mode === "EXPANDED" ? 412 : 675
    minimumHeight: sidecarBridge.mode === "EXPANDED" ? 806 : 300
    maximumHeight: sidecarBridge.mode === "EXPANDED" ? 806 : 300
    flags: Qt.Window | Qt.FramelessWindowHint
    color: "transparent"
    visible: false
    title: "PDLt Review Sidecar"

    readonly property bool expanded: sidecarBridge.mode === "EXPANDED"
    readonly property bool assetsReady: interRegular.status === FontLoader.Ready
        && interSemiBold.status === FontLoader.Ready
        && interBold.status === FontLoader.Ready
        && jetBrainsMono.status === FontLoader.Ready
        && expandAsset.status === Image.Ready
        && closeAsset.status === Image.Ready
        && externalAsset.status === Image.Ready
    readonly property string uiFamily: interRegular.name
    readonly property string monoFamily: jetBrainsMono.name

    FontLoader { id: interRegular; source: "../assets/fonts/Inter-Regular.ttf" }
    FontLoader { id: interSemiBold; source: "../assets/fonts/Inter-SemiBold.ttf" }
    FontLoader { id: interBold; source: "../assets/fonts/Inter-Bold.ttf" }
    FontLoader { id: jetBrainsMono; source: "../assets/fonts/JetBrainsMono-Regular.ttf" }
    Image { id: expandAsset; visible: false; source: "../assets/icons/expand.svg" }
    Image { id: closeAsset; visible: false; source: "../assets/icons/close.svg" }
    Image { id: externalAsset; visible: false; source: "../assets/icons/external-link.svg" }

    Rectangle {
        id: surface
        objectName: "sidecarSurface"
        anchors.fill: parent
        radius: DesignTokens.outerRadius
        color: root.expanded ? DesignTokens.expandedSurface : DesignTokens.outerSurface
        border.color: DesignTokens.outerBorder
        border.width: 1
        clip: true

        SidecarChrome {
            id: chrome
            anchors.left: parent.left
            anchors.right: parent.right
            height: root.expanded ? 49 : 44
            expanded: root.expanded
            uiFamily: root.uiFamily
            onExpandRequested: sidecarBridge.setMode("EXPANDED")
            onCloseRequested: sidecarBridge.requestClose()
        }

        ArtifactCard {
            id: artifactCard
            x: 8
            y: root.expanded ? 49 : 44
            width: root.expanded ? 397 : 402
            height: root.expanded ? 350 : 256
            expanded: root.expanded
            uiFamily: root.uiFamily
            monoFamily: root.monoFamily
            artifactLines: sidecarBridge.artifactLines
        }

        ReviewOptions {
            id: reviewOptions
            x: root.expanded ? 8 : 418
            y: root.expanded ? 408 : 44
            width: root.expanded ? 397 : 249
            height: root.expanded ? 398 : 256
            expanded: root.expanded
            uiFamily: root.uiFamily
            actions: sidecarBridge.actions
            onActionRequested: actionId => sidecarBridge.activateAction(actionId)
        }
    }

    function focusFirstAction() {
        reviewOptions.focusFirstAction()
    }
}
