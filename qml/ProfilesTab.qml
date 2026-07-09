// Copyright (c) 2026 Rafael
// "API Profiles" tab: manage multiple named OpenAI-compatible endpoint
// configs (e.g. "MiniMax", "GPT-4o", "Local Ollama") and pick which one is
// active.

import QtQuick 2.2
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

import UM 1.5 as UM

ColumnLayout
{
    id: profilesTab
    spacing: UM.Theme.getSize("default_margin").height

    // Index into manager.profiles currently loaded into the edit form below,
    // or -1 while creating a brand new profile.
    property int editingIndex: -1
    property string editingOriginalName: ""

    function loadProfileIntoForm(profile)
    {
        editingOriginalName = profile.name
        nameField.text = profile.name
        baseUrlField.text = profile.baseUrl
        modelField.text = profile.model
        apiKeyField.text = ""
    }

    function clearForm()
    {
        editingOriginalName = ""
        nameField.text = ""
        baseUrlField.text = "https://api.openai.com/v1"
        modelField.text = ""
        apiKeyField.text = ""
    }

    Label
    {
        text: catalog.i18nc("@label", "Saved profiles")
        font.bold: true
    }

    ScrollView
    {
        Layout.fillWidth: true
        Layout.preferredHeight: 160 * screenScaleFactor
        clip: true

        ListView
        {
            model: manager.profiles
            spacing: 2

            delegate: RowLayout
            {
                width: ListView.view.width

                RadioButton
                {
                    checked: modelData.name === manager.activeProfileName
                    onClicked: manager.selectProfile(modelData.name)
                }
                Label
                {
                    Layout.fillWidth: true
                    text: modelData.name + "  (" + modelData.model + ")"
                }
                Button
                {
                    text: catalog.i18nc("@action:button", "Edit")
                    onClicked: profilesTab.loadProfileIntoForm(modelData)
                }
                Button
                {
                    text: catalog.i18nc("@action:button", "Delete")
                    onClicked: manager.deleteProfile(modelData.name)
                }
            }
        }
    }

    Button
    {
        text: catalog.i18nc("@action:button", "+ New profile")
        onClicked: profilesTab.clearForm()
    }

    Label
    {
        text: editingOriginalName === ""
              ? catalog.i18nc("@label", "New profile")
              : catalog.i18nc("@label", "Editing: ") + editingOriginalName
        font.bold: true
    }

    GridLayout
    {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: UM.Theme.getSize("default_margin").width

        Label { text: catalog.i18nc("@label", "Profile name") }
        TextField
        {
            id: nameField
            Layout.fillWidth: true
            placeholderText: "e.g. GPT-4o, MiniMax, Local Ollama"
        }

        Label { text: catalog.i18nc("@label", "Base URL") }
        TextField
        {
            id: baseUrlField
            Layout.fillWidth: true
            placeholderText: "https://api.openai.com/v1"
        }

        Label { text: catalog.i18nc("@label", "API key") }
        TextField
        {
            id: apiKeyField
            Layout.fillWidth: true
            echoMode: TextInput.Password
            placeholderText: catalog.i18nc("@label", "leave blank to keep the current key")
        }

        Label { text: catalog.i18nc("@label", "Model") }
        TextField
        {
            id: modelField
            Layout.fillWidth: true
            placeholderText: "gpt-4o"
        }
    }

    Button
    {
        Layout.alignment: Qt.AlignRight
        text: catalog.i18nc("@action:button", "Save profile")
        onClicked:
        {
            manager.saveProfile(profilesTab.editingOriginalName, nameField.text, baseUrlField.text, apiKeyField.text, modelField.text)
            profilesTab.editingOriginalName = nameField.text
            apiKeyField.text = ""
        }
    }

    Item { Layout.fillHeight: true }

    Component.onCompleted: clearForm()
}
