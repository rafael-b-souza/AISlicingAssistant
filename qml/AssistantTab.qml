// Copyright (c) 2026 Rafael
// "Assistant" tab: state your intent, capture the model, review the AI's
// suggestions, and apply the ones you approve.

import QtQuick 2.2
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

import UM 1.5 as UM

ColumnLayout
{
    id: assistantTab
    // Reference to the root Dialog, so we can read/mutate its checkedKeys
    // map (owned there so it survives tab switches without being reset).
    property var dialog

    spacing: UM.Theme.getSize("default_margin").height

    Label
    {
        text: catalog.i18nc("@label", "What is this print for?")
    }
    TextArea
    {
        id: intentField
        Layout.fillWidth: true
        Layout.preferredHeight: 80 * screenScaleFactor
        placeholderText: catalog.i18nc("@label", "e.g. \"just checking if this fits, don't worry about strength\" or \"real structural part, prioritize strength\"")
        wrapMode: TextArea.Wrap
    }

    RowLayout
    {
        Layout.fillWidth: true
        Button
        {
            text: catalog.i18nc("@action:button", "Capture model && ask AI")
            enabled: !manager.busy
            onClicked: manager.requestSuggestions(intentField.text)
        }
        BusyIndicator
        {
            running: manager.busy
            visible: manager.busy
            implicitWidth: 24 * screenScaleFactor
            implicitHeight: 24 * screenScaleFactor
        }
        Item { Layout.fillWidth: true }
        Label
        {
            text: catalog.i18nc("@label", "Profile:") + " " + manager.activeProfileName
            opacity: 0.7
        }
    }

    Label
    {
        visible: manager.suggestions.length > 0
        text: manager.summary
        wrapMode: Text.Wrap
        Layout.fillWidth: true
    }

    ScrollView
    {
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true

        ListView
        {
            id: suggestionsList
            model: manager.suggestions
            spacing: UM.Theme.getSize("narrow_margin").height

            delegate: SuggestionRow
            {
                width: suggestionsList.width
                rowData: modelData
                initialChecked: assistantTab.dialog.checkedKeys[modelData.key] === true
                onCheckedChanged:
                {
                    // Mutate in place -- do NOT reassign dialog.checkedKeys
                    // here. Reassigning the whole object would re-trigger
                    // every delegate's "initialChecked" binding at once,
                    // which is what caused earlier binding-loop warnings.
                    assistantTab.dialog.checkedKeys[modelData.key] = checked
                }
            }
        }
    }

    Button
    {
        Layout.alignment: Qt.AlignRight
        text: catalog.i18nc("@action:button", "Apply selected")
        enabled: manager.suggestions.length > 0
        onClicked:
        {
            var approved = []
            for (var key in assistantTab.dialog.checkedKeys)
            {
                if (assistantTab.dialog.checkedKeys[key])
                {
                    approved.push(key)
                }
            }
            manager.applySettings(approved)
        }
    }
}
