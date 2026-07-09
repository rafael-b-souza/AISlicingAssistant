# Copyright (c) 2026 Rafael
# Main Extension class. This is the only file QML talks to -- everything
# else (snapshot capture, AI request/response, settings validation) lives in
# plain-Python helper modules so it stays testable without a running Cura.

import json
import os
import re
import stat
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal, pyqtProperty

from UM.Application import Application
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Message import Message
from UM.PluginRegistry import PluginRegistry
from UM.Resources import Resources
from UM.i18n import i18nCatalog

from . import SettingsSchema
from . import SnapshotRig
from . import AIClient
from . import ApplySettings

catalog = i18nCatalog("cura")

PREFERENCE_PROFILES = "ai_slicing_assistant/profiles"
PREFERENCE_ACTIVE_PROFILE = "ai_slicing_assistant/active_profile"
PREFERENCE_CUSTOM_INSTRUCTIONS = "ai_slicing_assistant/custom_instructions"

DEFAULT_PROFILE: Dict[str, str] = {"name": "Default", "base_url": "https://api.openai.com/v1", "model": "gpt-4o"}

KEYRING_SERVICE = "AISlicingAssistant"
# Fallback used when no OS keyring backend is reachable (e.g. Cura's Flatpak
# sandbox without D-Bus secrets access, or a remote/RDP session where the
# login keyring never gets unlocked). Stored in Cura's own per-version data
# directory -- never inside the plugin's source folder -- with permissions
# restricted to the owning user only. Keyed by profile name so each saved
# profile (e.g. "MiniMax", "GPT-4o", "Local Ollama") has its own key.
API_KEY_FILE_PREFIX = "ai_slicing_assistant_apikey_"


def _safe_profile_slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name) or "default"


class AISlicingAssistant(QObject, Extension):
    suggestionsReady = pyqtSignal()
    errorOccurred = pyqtSignal(str)
    busyChanged = pyqtSignal()
    profilesChanged = pyqtSignal()
    whitelistChanged = pyqtSignal()
    customInstructionsChanged = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()

        self.addMenuItem(catalog.i18nc("@item:inmenu", "AI Slicing Assistant"), self.showDialog)

        self._view = None
        self._validated_changes: List[ApplySettings.ValidatedChange] = []
        self._last_summary = ""
        self._busy = False

        preferences = Application.getInstance().getPreferences()
        preferences.addPreference(PREFERENCE_PROFILES, json.dumps([DEFAULT_PROFILE]))
        preferences.addPreference(PREFERENCE_ACTIVE_PROFILE, DEFAULT_PROFILE["name"])
        preferences.addPreference(SettingsSchema.PREFERENCE_ENABLED_KEYS, json.dumps(SettingsSchema.DEFAULT_WHITELIST))
        preferences.addPreference(PREFERENCE_CUSTOM_INSTRUCTIONS, "")

    # -- dialog lifecycle -----------------------------------------------

    def showDialog(self) -> None:
        if self._view is None:
            path = os.path.join(
                PluginRegistry.getInstance().getPluginPath("AISlicingAssistant"),
                "qml", "AIAssistantDialog.qml",
            )
            self._view = Application.getInstance().createQmlComponent(path, {"manager": self})
            if self._view is None:
                Logger.log("e", "[AISlicingAssistant] Failed to create QML component at %s", path)
                return
        self._view.show()

    # -- API profiles ------------------------------------------------------
    # A profile is {"name", "base_url", "model"}; its API key is stored
    # separately (keyring, or a restricted-permission local file keyed by
    # profile name) and never round-tripped back out to QML.

    def _getProfiles(self) -> List[Dict[str, str]]:
        raw = Application.getInstance().getPreferences().getValue(PREFERENCE_PROFILES)
        try:
            profiles = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            profiles = None
        if not isinstance(profiles, list) or not profiles:
            return [dict(DEFAULT_PROFILE)]
        return profiles

    def _setProfiles(self, profiles: List[Dict[str, str]]) -> None:
        if not profiles:
            profiles = [dict(DEFAULT_PROFILE)]
        Application.getInstance().getPreferences().setValue(PREFERENCE_PROFILES, json.dumps(profiles))
        self.profilesChanged.emit()

    @pyqtProperty("QVariantList", notify=profilesChanged)
    def profiles(self) -> List[Dict[str, str]]:
        return [{"name": p["name"], "baseUrl": p["base_url"], "model": p["model"]} for p in self._getProfiles()]

    @pyqtProperty(str, notify=profilesChanged)
    def activeProfileName(self) -> str:
        preferences = Application.getInstance().getPreferences()
        name = preferences.getValue(PREFERENCE_ACTIVE_PROFILE)
        existing_names = [p["name"] for p in self._getProfiles()]
        if name not in existing_names:
            name = existing_names[0]
            preferences.setValue(PREFERENCE_ACTIVE_PROFILE, name)
        return name

    def _getActiveProfile(self) -> Dict[str, str]:
        name = self.activeProfileName
        for profile in self._getProfiles():
            if profile["name"] == name:
                return profile
        return dict(DEFAULT_PROFILE)

    @pyqtSlot(str)
    def selectProfile(self, name: str) -> None:
        if name in [p["name"] for p in self._getProfiles()]:
            Application.getInstance().getPreferences().setValue(PREFERENCE_ACTIVE_PROFILE, name)
            self.profilesChanged.emit()

    @pyqtSlot(str, str, str, str, str)
    def saveProfile(self, original_name: str, name: str, base_url: str, api_key: str, model: str) -> None:
        """Create a new profile (original_name == "") or update an existing
        one (original_name == its current name, possibly being renamed).
        An empty api_key means "keep the currently stored key" -- so editing
        the URL/model of a profile doesn't force re-entering the key.
        """
        name = name.strip()
        if not name:
            self.errorOccurred.emit("Profile name cannot be empty.")
            return

        profiles = self._getProfiles()
        existing_names = [p["name"] for p in profiles]

        if original_name and original_name in existing_names:
            for profile in profiles:
                if profile["name"] == original_name:
                    profile["name"] = name
                    profile["base_url"] = base_url
                    profile["model"] = model
                    break
            if original_name != name:
                self._renameApiKey(original_name, name)
                if Application.getInstance().getPreferences().getValue(PREFERENCE_ACTIVE_PROFILE) == original_name:
                    Application.getInstance().getPreferences().setValue(PREFERENCE_ACTIVE_PROFILE, name)
        else:
            if name in existing_names:
                self.errorOccurred.emit(f"A profile named '{name}' already exists.")
                return
            profiles.append({"name": name, "base_url": base_url, "model": model})

        self._setProfiles(profiles)
        if api_key:
            self._storeApiKey(name, api_key)

    @pyqtSlot(str)
    def deleteProfile(self, name: str) -> None:
        profiles = self._getProfiles()
        if len(profiles) <= 1:
            self.errorOccurred.emit("Can't delete the last remaining profile.")
            return
        profiles = [p for p in profiles if p["name"] != name]
        self._deleteApiKey(name)
        self._setProfiles(profiles)
        if Application.getInstance().getPreferences().getValue(PREFERENCE_ACTIVE_PROFILE) == name:
            Application.getInstance().getPreferences().setValue(PREFERENCE_ACTIVE_PROFILE, profiles[0]["name"])
            self.profilesChanged.emit()

    # -- API key storage, keyed by profile name ----------------------------

    @staticmethod
    def _apiKeyFilePath(profile_name: str) -> str:
        return os.path.join(Resources.getDataStoragePath(), API_KEY_FILE_PREFIX + _safe_profile_slug(profile_name))

    def _storeApiKey(self, profile_name: str, api_key: str) -> None:
        try:
            import keyring
            keyring.set_password(KEYRING_SERVICE, profile_name, api_key)
            return
        except Exception as e:
            Logger.log("i", "[AISlicingAssistant] OS keyring unavailable (%s) -- "
                             "falling back to a local file with restricted permissions.", str(e))

        path = self._apiKeyFilePath(profile_name)
        try:
            with open(path, "w") as f:
                f.write(api_key)
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600, owner read/write only
        except OSError as e:
            Logger.log("e", "[AISlicingAssistant] Could not store API key in %s: %s", path, str(e))

    def _getApiKey(self, profile_name: str) -> str:
        try:
            import keyring
            value = keyring.get_password(KEYRING_SERVICE, profile_name)
            if value:
                return value
        except Exception as e:
            Logger.log("i", "[AISlicingAssistant] OS keyring unavailable (%s) -- "
                             "trying local fallback file.", str(e))

        path = self._apiKeyFilePath(profile_name)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return f.read().strip()
            except OSError as e:
                Logger.log("e", "[AISlicingAssistant] Could not read API key from %s: %s", path, str(e))
        return ""

    def _deleteApiKey(self, profile_name: str) -> None:
        try:
            import keyring
            keyring.delete_password(KEYRING_SERVICE, profile_name)
        except Exception:
            pass
        path = self._apiKeyFilePath(profile_name)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                Logger.log("w", "[AISlicingAssistant] Could not remove old API key file %s: %s", path, str(e))

    def _renameApiKey(self, old_name: str, new_name: str) -> None:
        api_key = self._getApiKey(old_name)
        if api_key:
            self._storeApiKey(new_name, api_key)
        self._deleteApiKey(old_name)

    # -- settings whitelist -------------------------------------------------

    @pyqtProperty("QVariantList", notify=whitelistChanged)
    def settingsCatalog(self) -> List[Dict[str, Any]]:
        global_stack = Application.getInstance().getGlobalContainerStack()
        if global_stack is None:
            return []
        enabled_keys = SettingsSchema.get_enabled_keys(Application.getInstance().getPreferences())
        return SettingsSchema.get_catalog_for_ui(global_stack, enabled_keys)

    @pyqtSlot("QVariantList")
    def saveEnabledKeys(self, keys: List[str]) -> None:
        SettingsSchema.set_enabled_keys(Application.getInstance().getPreferences(), keys)
        self.whitelistChanged.emit()

    # -- custom instructions ------------------------------------------------

    @pyqtProperty(str, notify=customInstructionsChanged)
    def customInstructions(self) -> str:
        return Application.getInstance().getPreferences().getValue(PREFERENCE_CUSTOM_INSTRUCTIONS)

    @pyqtSlot(str)
    def saveCustomInstructions(self, text: str) -> None:
        Application.getInstance().getPreferences().setValue(PREFERENCE_CUSTOM_INSTRUCTIONS, text)
        self.customInstructionsChanged.emit()

    # -- main flow: capture -> ask -> stage suggestions ------------------

    @pyqtSlot(str)
    def requestSuggestions(self, intent_text: str) -> None:
        global_stack = Application.getInstance().getGlobalContainerStack()
        if global_stack is None:
            self.errorOccurred.emit("No printer is currently active.")
            return

        profile = self._getActiveProfile()
        api_key = self._getApiKey(profile["name"])
        if not api_key:
            self.errorOccurred.emit(f"No API key configured for profile '{profile['name']}'. Set one in the assistant's settings first.")
            return

        images_b64 = SnapshotRig.capture_multi_angle()
        if not images_b64:
            self.errorOccurred.emit("Could not capture any snapshot -- is a model loaded on the build plate?")
            return

        preferences = Application.getInstance().getPreferences()
        enabled_keys = SettingsSchema.get_enabled_keys(preferences)
        settings_context = SettingsSchema.get_all_bounds(global_stack, enabled_keys)
        custom_instructions = preferences.getValue(PREFERENCE_CUSTOM_INSTRUCTIONS)

        self._setBusy(True)

        def on_success(response: AIClient.AIResponse) -> None:
            self._setBusy(False)
            if response.raw_error:
                self.errorOccurred.emit("AI response could not be understood: " + response.raw_error)
                return
            self._last_summary = response.summary
            self._validated_changes = ApplySettings.validate(global_stack, response.changes, enabled_keys)
            self.suggestionsReady.emit()

        def on_error(error_text: str) -> None:
            self._setBusy(False)
            self.errorOccurred.emit("Request failed: " + error_text)

        AIClient.send_request_async(
            base_url=profile["base_url"],
            api_key=api_key,
            model=profile["model"],
            intent_text=intent_text,
            images_b64=images_b64,
            settings_context=settings_context,
            on_success=on_success,
            on_error=on_error,
            custom_instructions=custom_instructions,
        )

    # -- review / apply ---------------------------------------------------

    @pyqtProperty(str, notify=suggestionsReady)
    def summary(self) -> str:
        return self._last_summary

    @pyqtProperty("QVariantList", notify=suggestionsReady)
    def suggestions(self) -> List[Dict[str, Any]]:
        rows = []
        for vc in self._validated_changes:
            rows.append({
                "key": vc.key,
                "label": (vc.bounds or {}).get("label") or vc.key,
                "unit": (vc.bounds or {}).get("unit") or "",
                "currentValue": (vc.bounds or {}).get("current_value"),
                "proposedValue": vc.resolved_value,
                "reasoning": vc.reasoning,
                "status": vc.status,
                "note": vc.note,
                "selectable": not vc.status.startswith("REJECTED"),
                "defaultChecked": vc.status == ApplySettings.STATUS_OK,
            })
        return rows

    @pyqtSlot("QVariantList")
    def applySettings(self, approved_keys: List[str]) -> None:
        global_stack = Application.getInstance().getGlobalContainerStack()
        if global_stack is None:
            self.errorOccurred.emit("No printer is currently active.")
            return

        applied = ApplySettings.apply(global_stack, self._validated_changes, set(approved_keys))
        Message(
            text=catalog.i18nc("@info:status", "Applied {count} setting(s). Use Cura's Slice button when ready.").format(count=len(applied)),
            title=catalog.i18nc("@info:title", "AI Slicing Assistant"),
        ).show()
        self._validated_changes = []
        self.suggestionsReady.emit()

    # -- busy state --------------------------------------------------------

    def _setBusy(self, value: bool) -> None:
        self._busy = value
        self.busyChanged.emit()

    @pyqtProperty(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy
