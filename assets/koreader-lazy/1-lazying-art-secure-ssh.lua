-- Secure appliance defaults for this Kindle. KOReader loads user patches
-- before its plugins, so the SSH plugin sees these values on every launch.
local DataStorage = require("datastorage")
local settings = require("luasettings"):open(
    DataStorage:getDataDir() .. "/settings.reader.lua")

settings:makeFalse("SSH_allow_no_password")
settings:makeTrue("SSH_key_only_auth")
settings:makeTrue("SSH_autostart")
settings:makeTrue("SSH_force_kill_clients")
settings:saveSetting("SSH_port", "2222")

-- Preserve the Kindle's saved Wi-Fi state; KOReader must not turn it off on
-- exit or attempt to replace the system Wi-Fi profile.
settings:makeFalse("auto_disable_wifi")

local disabled_plugins = settings:readSetting("plugins_disabled")
if type(disabled_plugins) == "table" and disabled_plugins.SSH ~= nil then
    disabled_plugins.SSH = nil
    settings:saveSetting("plugins_disabled", disabled_plugins)
end

settings:flush()
return {}
