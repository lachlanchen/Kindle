#!/bin/sh
# Fail-closed installer for the audited PW5SE 5.15.1 only.
# This script never uses /mnt/us/emergency.sh and never starts KOReader itself.

set -u

EXPECTED_FIRMWARE="5.15.1"
JOB_NAME="lazying-koreader"
JOB_PATH="/etc/upstart/${JOB_NAME}.conf"
JOB_SHA256="87381c8cb810b3e8606c97b5ad913a1be5f49c7a4ba6f46f66b6ae3e28e95dbd"
LEGACY_JOB_SHA256="2de0232b971926b7e70d913a27ba76168ed69760504ae2a90947e4402e7e5828"
DEFAULT_CANDIDATE="/tmp/lazying-koreader-autostart.conf"
DISABLE_MARKER="/mnt/us/DISABLE_KOREADER_AUTOSTART"
STANDARD_MARKER="/mnt/us/_DISABLE_KOREADER_AUTOSTART"
FRAMEWORK_STOP_MARKER="/mnt/us/_DISABLE_KOREADER_AUTOSTART_FRAMEWORK_STOP"
EMERGENCY_SCRIPT="/mnt/us/emergency.sh"
KOREADER_LAUNCHER="/mnt/us/koreader/koreader.sh"

ROOT_WRITE_ACTIVE=0
RESTORE_ROOT_RO=0
OWNED_JOB_TMP=0
JOB_TMP=""

say() {
    printf '%s\n' "$*"
}

die() {
    say "error=$*" >&2
    exit 1
}

file_sha256() {
    sha256sum "$1" 2>/dev/null | awk '{print $1}'
}

firmware_version() {
    sed -n 's/^Kindle[[:space:]]*\([0-9][0-9.]*\).*$/\1/p' \
        /etc/prettyversion.txt 2>/dev/null | head -n 1
}

job_state() {
    if [ ! -e "${JOB_PATH}" ]; then
        if [ -L "${JOB_PATH}" ]; then
            say "foreign"
        else
            say "absent"
        fi
    elif [ -L "${JOB_PATH}" ] || [ ! -f "${JOB_PATH}" ]; then
        say "foreign"
    else
        installed_hash="$(file_sha256 "${JOB_PATH}")"
        if [ "${installed_hash}" = "${JOB_SHA256}" ]; then
            say "owned"
        elif [ "${installed_hash}" = "${LEGACY_JOB_SHA256}" ]; then
            say "owned_legacy"
        else
            say "foreign"
        fi
    fi
}

marker_kind() {
    marker_path="$1"
    if [ -L "${marker_path}" ]; then
        say "symlink"
    elif [ -f "${marker_path}" ]; then
        say "file"
    elif [ -d "${marker_path}" ]; then
        say "directory"
    elif [ -e "${marker_path}" ]; then
        say "other"
    else
        say "absent"
    fi
}

marker_switch_state() {
    active_kind="$(marker_kind "${DISABLE_MARKER}")"
    standard_kind="$(marker_kind "${STANDARD_MARKER}")"
    framework_stop_kind="$(marker_kind "${FRAMEWORK_STOP_MARKER}")"

    case "${active_kind}" in
        absent|file) ;;
        *) say "unsafe_active_${active_kind}"; return 0 ;;
    esac
    case "${standard_kind}" in
        absent|file) ;;
        *) say "unsafe_standard_${standard_kind}"; return 0 ;;
    esac
    case "${framework_stop_kind}" in
        absent|file) ;;
        *) say "unsafe_framework_stop_${framework_stop_kind}"; return 0 ;;
    esac

    present=0
    [ "${active_kind}" = "file" ] && present=$((present + 1))
    [ "${standard_kind}" = "file" ] && present=$((present + 1))
    [ "${framework_stop_kind}" = "file" ] && present=$((present + 1))
    if [ "${present}" -eq 0 ]; then
        say "missing_all"
    elif [ "${present}" -ne 1 ]; then
        say "ambiguous_multiple_present"
    elif [ "${active_kind}" = "file" ]; then
        say "disabled"
    elif [ "${standard_kind}" = "file" ]; then
        say "enabled_standard"
    else
        say "enabled_framework_stop"
    fi
}

root_is_rw() {
    awk '
        $2 == "/" {
            found = 1
            count = split($4, option, ",")
            for (i = 1; i <= count; i++) {
                if (option[i] == "rw") exit 0
            }
            exit 1
        }
        END { if (!found) exit 1 }
    ' /proc/mounts
}

cleanup() {
    rc=$?
    trap - 0 1 2 15
    if [ "${ROOT_WRITE_ACTIVE}" -eq 1 ]; then
        if [ "${OWNED_JOB_TMP}" -eq 1 ] && [ -n "${JOB_TMP}" ]; then
            rm -f "${JOB_TMP}" || rc=1
        fi
        sync
        if [ "${RESTORE_ROOT_RO}" -eq 1 ]; then
            mntroot ro >/dev/null 2>&1 || rc=1
        fi
    fi
    exit "${rc}"
}

trap cleanup 0
trap 'exit 130' 1 2 15

begin_root_write() {
    ROOT_WRITE_ACTIVE=1
    if root_is_rw; then
        RESTORE_ROOT_RO=0
    else
        RESTORE_ROOT_RO=1
        mntroot rw >/dev/null 2>&1 || die "could_not_remount_root_rw"
    fi
}

finish_root_write() {
    sync
    if [ "${RESTORE_ROOT_RO}" -eq 1 ]; then
        mntroot ro >/dev/null 2>&1 || die "could_not_restore_root_ro"
    fi
    ROOT_WRITE_ACTIVE=0
    RESTORE_ROOT_RO=0
    OWNED_JOB_TMP=0
    JOB_TMP=""
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "missing_command_$1"
}

reload_upstart() {
    attempt=1
    while [ "${attempt}" -le 5 ]; do
        if initctl reload-configuration >/dev/null 2>&1; then
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 1
    done
    return 1
}

reload_and_require_registered_job() {
    reload_upstart || return 1
    attempt=1
    while [ "${attempt}" -le 5 ]; do
        if initctl status "${JOB_NAME}" >/dev/null 2>&1; then
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 1
    done
    return 1
}

assert_owned_or_absent_job() {
    state="$(job_state)"
    case "${state}" in
        absent|owned|owned_legacy) ;;
        *) die "foreign_upstart_job_refused" ;;
    esac
}

assert_owned_job() {
    [ "$(job_state)" = "owned" ] || die "owned_upstart_job_required"
}

assert_audited_runtime() {
    firmware="$(firmware_version)"
    [ "${firmware}" = "${EXPECTED_FIRMWARE}" ] || \
        die "firmware_mismatch_expected_${EXPECTED_FIRMWARE}"

    [ -d /etc/upstart ] || die "missing_etc_upstart"
    [ -f /etc/upstart/kmc.conf ] || die "missing_kmc_job"
    [ -f /etc/upstart/home_wait.conf ] || die "missing_home_wait_job"
    [ -f /etc/upstart/lab126_gui.conf ] || die "missing_lab126_gui_job"
    [ -f /etc/upstart/kppmainapp.conf ] || die "missing_kppmainapp_job"
    grep -Fq 'start on framework_ready' /etc/upstart/kmc.conf || \
        die "unexpected_framework_ready_boundary"
    grep -Fq 'lipc-wait-event' /etc/upstart/home_wait.conf || \
        die "unexpected_home_wait_boundary"
    grep -Fq 'appStarted' /etc/upstart/home_wait.conf || \
        die "unexpected_home_wait_event"

    require_command awk
    require_command chmod
    require_command chown
    require_command cp
    require_command grep
    require_command head
    require_command initctl
    require_command lipc-wait-event
    require_command lipc-set-prop
    require_command mntroot
    require_command mv
    require_command pidof
    require_command rm
    require_command rmdir
    require_command sed
    require_command sha256sum
    require_command sleep
    require_command sync

    # Kindle 5.15.1 ships Upstart 0.6.6, whose initctl has no show-config
    # command. A known stock job status is the live daemon capability check.
    initctl status kmc >/dev/null 2>&1 || \
        die "upstart_stock_job_status_unavailable"
    { [ ! -e "${EMERGENCY_SCRIPT}" ] && [ ! -L "${EMERGENCY_SCRIPT}" ]; } || \
        die "root_emergency_script_present"
    { [ -f "${KOREADER_LAUNCHER}" ] && [ ! -L "${KOREADER_LAUNCHER}" ]; } || \
        die "koreader_launcher_missing_or_symlink"
    assert_owned_or_absent_job
}

ensure_disabled() {
    switch_state="$(marker_switch_state)"
    case "${switch_state}" in
        disabled)
            return 0
            ;;
        enabled_standard)
            rename_marker_exact \
                "${STANDARD_MARKER}" \
                "${DISABLE_MARKER}" \
                "disabled"
            ;;
        enabled_framework_stop)
            rename_marker_exact \
                "${FRAMEWORK_STOP_MARKER}" \
                "${DISABLE_MARKER}" \
                "disabled"
            ;;
        missing_all)
            umask 022
            : >"${DISABLE_MARKER}" || die "could_not_create_initial_disable_marker"
            sync
            [ "$(marker_switch_state)" = "disabled" ] || \
                die "initial_disable_marker_not_durable"
            ;;
        ambiguous_multiple_present)
            die "ambiguous_multiple_markers_refused"
            ;;
        unsafe_*)
            die "unsafe_marker_type_refused_${switch_state}"
            ;;
        *)
            die "unknown_marker_switch_state"
            ;;
    esac
}

ensure_legacy_fail_closed_before_marker_validation() {
    [ "$(job_state)" = "owned_legacy" ] || return 0

    # V1 knows only DISABLE_MARKER and treats any object at that path as a
    # stop condition. Valid v2 topologies are handled normally below. If a
    # malformed new three-marker topology has no active object, first create a
    # conservative regular disable marker, preserving every suspect object for
    # audit, and only then let strict v2 validation refuse the upgrade.
    legacy_switch_state="$(marker_switch_state)"
    case "${legacy_switch_state}" in
        disabled|enabled_standard|enabled_framework_stop|missing_all)
            return 0
            ;;
    esac

    legacy_active_kind="$(marker_kind "${DISABLE_MARKER}")"
    if [ "${legacy_active_kind}" = "absent" ]; then
        umask 022
        : >"${DISABLE_MARKER}" || die "legacy_fail_closed_marker_create_failed"
        sync
        [ "$(marker_kind "${DISABLE_MARKER}")" = "file" ] || \
            die "legacy_fail_closed_marker_not_durable"
    fi

    # The exact v1 job gates on -e || -L, so any existing active object is
    # already fail-closed. Do not rename or delete that object here.
    if [ ! -e "${DISABLE_MARKER}" ] && [ ! -L "${DISABLE_MARKER}" ]; then
        die "legacy_job_could_not_be_fail_closed"
    fi
    say "warning=legacy_job_fail_closed_before_invalid_marker_refusal" >&2
}

rename_marker_exact() {
    marker_from="$1"
    marker_to="$2"
    expected_switch_state="$3"
    marker_from_kind="$(marker_kind "${marker_from}")"
    marker_to_kind="$(marker_kind "${marker_to}")"

    case "${marker_from_kind}" in
        file) ;;
        symlink) die "source_marker_symlink_refused" ;;
        *) die "source_marker_not_renameable" ;;
    esac
    [ "${marker_to_kind}" = "absent" ] || die "destination_marker_already_exists"

    # Both names are in /mnt/us, so this is one same-filesystem rename. The
    # marker and any contents are preserved; enable/disable never deletes it.
    mv "${marker_from}" "${marker_to}" || die "marker_atomic_rename_failed"
    sync
    [ "$(marker_kind "${marker_from}")" = "absent" ] || \
        die "source_marker_remained_after_rename"
    [ "$(marker_kind "${marker_to}")" = "${marker_from_kind}" ] || \
        die "destination_marker_type_changed"
    [ "$(marker_switch_state)" = "${expected_switch_state}" ] || \
        die "marker_switch_state_mismatch_after_rename"
}

ensure_mode() {
    requested_mode="$1"
    case "${requested_mode}" in
        standard)
            requested_marker="${STANDARD_MARKER}"
            expected_state="enabled_standard"
            ;;
        framework_stop)
            requested_marker="${FRAMEWORK_STOP_MARKER}"
            expected_state="enabled_framework_stop"
            ;;
        *) die "unknown_requested_mode" ;;
    esac

    switch_state="$(marker_switch_state)"
    case "${switch_state}" in
        "${expected_state}")
            return 0
            ;;
        disabled)
            rename_marker_exact \
                "${DISABLE_MARKER}" \
                "${requested_marker}" \
                "${expected_state}"
            ;;
        enabled_standard)
            rename_marker_exact \
                "${STANDARD_MARKER}" \
                "${requested_marker}" \
                "${expected_state}"
            ;;
        enabled_framework_stop)
            rename_marker_exact \
                "${FRAMEWORK_STOP_MARKER}" \
                "${requested_marker}" \
                "${expected_state}"
            ;;
        missing_all)
            die "marker_switch_missing_refusing_enable"
            ;;
        ambiguous_multiple_present)
            die "ambiguous_multiple_markers_refused"
            ;;
        unsafe_*)
            die "unsafe_marker_type_refused_${switch_state}"
            ;;
        *)
            die "unknown_marker_switch_state"
            ;;
    esac
}

print_status() {
    firmware="$(firmware_version)"
    state="$(job_state)"
    active_marker="$(marker_kind "${DISABLE_MARKER}")"
    standard_marker="$(marker_kind "${STANDARD_MARKER}")"
    framework_stop_marker="$(marker_kind "${FRAMEWORK_STOP_MARKER}")"
    switch_state="$(marker_switch_state)"

    say "firmware=${firmware:-unknown}"
    say "job=${state}"
    say "disable_marker=${active_marker}"
    say "standard_marker=${standard_marker}"
    say "framework_stop_marker=${framework_stop_marker}"
    say "marker_switch=${switch_state}"
    if [ -e "${EMERGENCY_SCRIPT}" ] || [ -L "${EMERGENCY_SCRIPT}" ]; then
        say "emergency_script=present"
    else
        say "emergency_script=absent"
    fi
    if [ -f "${KOREADER_LAUNCHER}" ] && [ ! -L "${KOREADER_LAUNCHER}" ]; then
        say "koreader_launcher=present"
    else
        say "koreader_launcher=absent"
    fi

    if [ "${state}" = "owned" ] && [ "${switch_state}" = "enabled_standard" ] && \
        [ ! -e "${EMERGENCY_SCRIPT}" ] && [ ! -L "${EMERGENCY_SCRIPT}" ] && \
        [ -f "${KOREADER_LAUNCHER}" ] && [ ! -L "${KOREADER_LAUNCHER}" ]; then
        say "autostart=enabled_standard_next_boot"
    elif [ "${state}" = "owned" ] && [ "${switch_state}" = "enabled_framework_stop" ] && \
        [ ! -e "${EMERGENCY_SCRIPT}" ] && [ ! -L "${EMERGENCY_SCRIPT}" ] && \
        [ -f "${KOREADER_LAUNCHER}" ] && [ ! -L "${KOREADER_LAUNCHER}" ]; then
        say "autostart=enabled_framework_stop_next_boot"
    elif [ "${state}" = "owned" ] && [ "${switch_state}" != "disabled" ] && \
        [ ! -e "${EMERGENCY_SCRIPT}" ] && [ ! -L "${EMERGENCY_SCRIPT}" ] && \
        [ -f "${KOREADER_LAUNCHER}" ] && [ ! -L "${KOREADER_LAUNCHER}" ]; then
        say "autostart=unsafe_marker_state"
    else
        say "autostart=disabled_or_unavailable"
    fi
}

install_job() {
    candidate="${1:-${DEFAULT_CANDIDATE}}"
    assert_audited_runtime
    { [ -f "${candidate}" ] && [ ! -L "${candidate}" ]; } || \
        die "candidate_job_missing_or_symlink"
    [ "$(file_sha256 "${candidate}")" = "${JOB_SHA256}" ] || \
        die "candidate_job_hash_mismatch"

    # Stage every install disabled. Enabling is a separate explicit action.
    ensure_legacy_fail_closed_before_marker_validation
    ensure_disabled
    original_state="$(job_state)"
    if [ "${original_state}" = "owned" ]; then
        reload_and_require_registered_job || \
            die "upstart_reload_or_registration_failed"
        say "result=already_installed_disabled"
        print_status
        return 0
    fi

    begin_root_write
    JOB_TMP="${JOB_PATH}.lazying-art.$$"
    { [ ! -e "${JOB_TMP}" ] && [ ! -L "${JOB_TMP}" ]; } || \
        die "owned_job_temp_path_exists"
    # Claim this previously absent exact path before cp so a partial copy is
    # removed by the root-restoration trap.
    OWNED_JOB_TMP=1
    cp "${candidate}" "${JOB_TMP}" || die "job_copy_failed"
    [ "$(file_sha256 "${JOB_TMP}")" = "${JOB_SHA256}" ] || \
        die "job_temp_hash_mismatch"
    chown root:root "${JOB_TMP}" || die "job_chown_failed"
    chmod 0644 "${JOB_TMP}" || die "job_chmod_failed"
    current_state="$(job_state)"
    [ "${current_state}" = "${original_state}" ] || \
        die "job_changed_during_install"
    case "${current_state}" in
        absent)
            { [ ! -e "${JOB_PATH}" ] && [ ! -L "${JOB_PATH}" ]; } || \
                die "job_path_appeared_during_install"
            ;;
        owned_legacy) ;;
        *) die "unexpected_job_state_during_install" ;;
    esac
    mv -f "${JOB_TMP}" "${JOB_PATH}" || die "job_atomic_publish_failed"
    OWNED_JOB_TMP=0
    JOB_TMP=""
    [ "$(job_state)" = "owned" ] || die "published_job_hash_mismatch"
    finish_root_write

    # Reloading configuration does not start a job; the disable marker remains.
    reload_and_require_registered_job || \
        die "upstart_reload_or_registration_failed_job_remains_disabled"
    if [ "${original_state}" = "owned_legacy" ]; then
        say "result=upgraded_disabled"
    else
        say "result=installed_disabled"
    fi
    print_status
}

enable_job() {
    requested_mode="$1"
    assert_audited_runtime
    assert_owned_job
    initctl status "${JOB_NAME}" >/dev/null 2>&1 || \
        die "installed_job_not_registered"
    ensure_mode "${requested_mode}"
    say "result=enabled_${requested_mode}_for_next_boot"
    print_status
}

disable_job() {
    ensure_legacy_fail_closed_before_marker_validation
    ensure_disabled
    say "result=disabled_for_next_boot"
    print_status
}

uninstall_job() {
    # Native UI is the recovery default even if later checks refuse removal.
    ensure_legacy_fail_closed_before_marker_validation
    ensure_disabled
    state="$(job_state)"
    [ "${state}" != "foreign" ] || die "foreign_upstart_job_refused"
    if [ "${state}" = "absent" ]; then
        say "result=already_uninstalled_disabled"
        print_status
        return 0
    fi

    begin_root_write
    current_state="$(job_state)"
    { [ "${current_state}" = "owned" ] || [ "${current_state}" = "owned_legacy" ]; } || \
        die "job_changed_before_uninstall"
    rm -f "${JOB_PATH}" || die "job_remove_failed"
    [ ! -e "${JOB_PATH}" ] || die "job_still_present"
    finish_root_write
    reload_upstart || \
        die "upstart_reload_failed_job_is_removed"
    say "result=uninstalled_disabled"
    print_status
}

usage() {
    say "usage: $0 audit|status|install|enable|enable-standard|enable-framework-stop|disable|uninstall [candidate-conf]"
}

action="${1:-status}"
case "${action}" in
    audit)
        assert_audited_runtime
        say "result=audit_passed"
        print_status
        ;;
    status)
        print_status
        ;;
    install)
        install_job "${2:-${DEFAULT_CANDIDATE}}"
        ;;
    enable|enable-standard)
        enable_job standard
        ;;
    enable-framework-stop)
        enable_job framework_stop
        ;;
    disable)
        disable_job
        ;;
    uninstall)
        uninstall_job
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
