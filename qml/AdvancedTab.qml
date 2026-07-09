// Copyright (c) 2026 Rafael
// "Advanced" tab: pick which settings the AI is allowed to touch (a
// curated catalog, not the full ~400 Cura exposes), and add optional
// custom instructions appended to the assistant's system prompt.

import QtQuick 2.2
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

import UM 1.5 as UM

ColumnLayout
{
    id: advancedTab
    spacing: UM.Theme.getSize("default_margin").height

    // key -> bool, built once when settingsCatalog first loads and mutated
    // in place by each checkbox from then on (see SuggestionRow.qml's
    // comments for why this avoids QML binding loops).
    property var enabledMap: ({})

    Label
    {
        text: catalog.i18nc("@label", "Settings the AI is allowed to suggest changes for")
        font.bold: true
    }

    ScrollView
    {
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true

        ColumnLayout
        {
            width: parent.width
            spacing: UM.Theme.getSize("narrow_margin").height

            Repeater
            {
                model: manager.settingsCatalog

                ColumnLayout
                {
                    Layout.fillWidth: true
                    spacing: 2

                    Label
                    {
                        text: modelData.category
                        font.bold: true
                    }

                    Repeater
                    {
                        model: modelData.settings

                        CheckBox
                        {
                            text: modelData.label
                            Component.onCompleted:
                            {
                                checked = modelData.enabled
                                advancedTab.enabledMap[modelData.key] = modelData.enabled
                            }
                            onCheckedChanged: advancedTab.enabledMap[modelData.key] = checked
                        }
                    }
                }
            }
        }
    }

    Button
    {
        Layout.alignment: Qt.AlignRight
        text: catalog.i18nc("@action:button", "Save whitelist")
        onClicked:
        {
            var keys = []
            for (var key in advancedTab.enabledMap)
            {
                if (advancedTab.enabledMap[key])
                {
                    keys.push(key)
                }
            }
            manager.saveEnabledKeys(keys)
        }
    }

    Label
    {
        text: catalog.i18nc("@label", "Custom instructions (optional, appended to the assistant's system prompt)")
        font.bold: true
    }
    TextArea
    {
        id: customInstructionsField
        Layout.fillWidth: true
        Layout.preferredHeight: 100 * screenScaleFactor
        wrapMode: TextArea.Wrap
        placeholderText: catalog.i18nc("@label", "e.g. \"always prefer gyroid infill\" or \"assume PETG unless told otherwise\"")
        Component.onCompleted: text = manager.customInstructions
    }
    Button
    {
        Layout.alignment: Qt.AlignRight
        text: catalog.i18nc("@action:button", "Save instructions")
        onClicked: manager.saveCustomInstructions(customInstructionsField.text)
    }
}
