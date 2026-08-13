-- Keep Amazon's ambient-brightness controller from competing with KOReader.
-- The opt-in file is intentionally simple and USB-visible: a regular file at
-- /mnt/us/ENABLE_AMAZON_AUTO_BRIGHTNESS enables Amazon ALS; absence, a link,
-- or any other file type keeps brightness manual.
local Device = require("device")
local UIManager = require("ui/uimanager")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")

if not Device:isKindle() or Device.model ~= "KindlePaperWhite5SE" then
    return {}
end

local powerd = Device:getPowerDevice()
local opt_in_path = "/mnt/us/ENABLE_AMAZON_AUTO_BRIGHTNESS"

local function desiredAutoMode()
    return lfs.symlinkattributes(opt_in_path, "mode") == "file" and 1 or 0
end

local function applyAutoMode(context)
    if not powerd.lipc_handle then
        logger.warn("lazying.art ambient brightness: no LIPC handle during", context)
        return
    end
    local desired = desiredAutoMode()
    local ok, err = pcall(function()
        powerd.lipc_handle:set_int_property("com.lab126.powerd", "flAuto", desired)
    end)
    if ok then
        logger.info("lazying.art ambient brightness: applied mode", desired, "during", context)
    else
        logger.warn("lazying.art ambient brightness: apply failed during", context, err)
    end
end

local original_after_resume = powerd.afterResume
powerd.afterResume = function(self, ...)
    local result = original_after_resume(self, ...)
    -- Let Amazon finish restoring its frontlight state, then win the race.
    UIManager:scheduleIn(1, function() applyAutoMode("resume") end)
    return result
end

UIManager:scheduleIn(0, function() applyAutoMode("startup") end)

return {}
