// Copyright (c) 2026 Rafael
// One row in the review table: current -> proposed value, the AI's
// reasoning, and a checkbox to approve applying it. Rejected suggestions
// are shown (with the reason) but cannot be checked.

import QtQuick 2.2
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.1

import UM 1.5 as UM

Rectangle
{
    id: root
    property var rowData
    // One-time initial value from the caller -- NOT a persistent binding.
    // "checked" below is a plain property that starts from this and is then
    // only ever changed by the checkbox itself.
    property bool initialChecked: false
    property bool checked: false
    // Note: no explicit "signal checkedChanged()" here -- QML already
    // auto-generates a change signal for every declared property, and a
    // manual redeclaration is a "duplicate signal" error that silently
    // breaks the whole component (and thus the dialog that loads it).

    Component.onCompleted: checked = initialChecked

    height: contentColumn.implicitHeight + 2 * UM.Theme.getSize("narrow_margin").height
    color: rowData.status === "OK" ? "transparent"
           : rowData.status === "CLAMPED" ? UM.Theme.getColor("setting_validation_warning_background")
           : UM.Theme.getColor("setting_validation_error_background")
    border.width: 1
    border.color: UM.Theme.getColor("lining")
    radius: 2

    ColumnLayout
    {
        id: contentColumn
        anchors
        {
            left: parent.left
            right: parent.right
            top: parent.top
            margins: UM.Theme.getSize("narrow_margin").width
        }
        spacing: 2

        RowLayout
        {
            Layout.fillWidth: true

            CheckBox
            {
                id: checkbox
                enabled: rowData.selectable
                onCheckedChanged: root.checked = checked
                Component.onCompleted: checked = root.checked
            }

            Label
            {
                text: rowData.label
                font.bold: true
            }

            Label
            {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignRight
                text: rowData.currentValue + " " + rowData.unit + "  ->  " + rowData.proposedValue + " " + rowData.unit
            }
        }

        Label
        {
            Layout.fillWidth: true
            text: rowData.reasoning
            wrapMode: Text.Wrap
            font.italic: true
            opacity: 0.8
        }

        Label
        {
            visible: rowData.note !== ""
            Layout.fillWidth: true
            text: rowData.note
            wrapMode: Text.Wrap
            color: rowData.status === "OK" ? UM.Theme.getColor("text") : UM.Theme.getColor("error")
            font.pixelSize: UM.Theme.getFont("small").pixelSize
        }
    }
}
