// Copyright (c) 2026 Rafael
// Main dialog for the AI Slicing Assistant: three tabs -- the assistant
// flow itself, API profile management, and advanced settings (whitelist +
// custom instructions).

import QtQuick 2.2
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

import UM 1.5 as UM

UM.Dialog
{
    id: dialog

    title: catalog.i18nc("@title:window", "AI Slicing Assistant")
    width: 760 * screenScaleFactor
    height: 700 * screenScaleFactor
    minimumWidth: 560 * screenScaleFactor
    minimumHeight: 520 * screenScaleFactor
    backgroundColor: UM.Theme.getColor("main_background")

    property var checkedKeys: ({})

    // UM.Dialog only accepts a single content Item -- everything (the
    // non-visual catalog/Connections objects included) has to live inside
    // one top-level Item, not as separate siblings directly under the
    // Dialog (that fails with "Cannot assign object to list property
    // 'contents'").
    Item
    {
        id: base
        anchors.fill: parent

        UM.I18nCatalog { id: catalog; name: "cura" }

        Connections
        {
            target: manager
            function onErrorOccurred(message)
            {
                errorLabel.text = message
                errorLabel.visible = true
            }
            function onSuggestionsReady()
            {
                errorLabel.visible = false
                dialog.checkedKeys = {}
                for (var i = 0; i < manager.suggestions.length; i++)
                {
                    var row = manager.suggestions[i]
                    dialog.checkedKeys[row.key] = row.defaultChecked
                }
            }
        }

        ColumnLayout
        {
            anchors.fill: parent
            spacing: UM.Theme.getSize("narrow_margin").height

            TabBar
            {
                id: tabBar
                Layout.fillWidth: true
                TabButton { text: catalog.i18nc("@title:tab", "Assistant") }
                TabButton { text: catalog.i18nc("@title:tab", "API Profiles") }
                TabButton { text: catalog.i18nc("@title:tab", "Advanced") }
            }

            // Shared across tabs (not just inside AssistantTab's own id
            // scope) so Connections.onErrorOccurred above can reach it
            // regardless of which tab is currently visible.
            Label
            {
                id: errorLabel
                Layout.fillWidth: true
                visible: false
                color: UM.Theme.getColor("error")
                wrapMode: Text.Wrap
            }

            StackLayout
            {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: tabBar.currentIndex

                AssistantTab
                {
                    dialog: dialog
                }
                ProfilesTab
                {
                }
                AdvancedTab
                {
                }
            }
        }
    }
}
