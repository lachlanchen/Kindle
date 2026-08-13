#!/bin/sh
# Narrow, reversible guard for one observed KOReader v2026.07.1 PW5SE crash.
# It never starts, stops, or signals KOReader; changes load on the next launch.

set -u

EXPECTED_FIRMWARE="5.15.1"
TARGET="/mnt/us/koreader/frontend/device/gesturedetector.lua"
ORIGINAL_SHA256="3a2d733a66f94e5cb1cc003c7ba736a03006e7c9242211adc243d74bc2c67db8"
PATCHED_SHA256="8abc677d5eee22ae59f5454530eb79831f0e0f96717536edb76589de40f84ad5"
ROLLBACK_DIR="/mnt/us/koreader/.lazying-art-stability"
ROLLBACK="${ROLLBACK_DIR}/gesturedetector-v2026.07.1.original.lua"
ROLLBACK_STAGE="${ROLLBACK_DIR}/.gesturedetector-v2026.07.1.original.lua.stage"

TARGET_TMP=""
ROLLBACK_TMP=""

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

path_kind() {
    path="$1"
    if [ -L "${path}" ]; then
        say symlink
    elif [ -f "${path}" ]; then
        say file
    elif [ -d "${path}" ]; then
        say directory
    elif [ -e "${path}" ]; then
        say other
    else
        say absent
    fi
}

cleanup() {
    rc=$?
    trap - 0 1 2 15
    [ -z "${TARGET_TMP}" ] || rm -f "${TARGET_TMP}" || rc=1
    [ -z "${ROLLBACK_TMP}" ] || rm -f "${ROLLBACK_TMP}" || rc=1
    exit "${rc}"
}

trap cleanup 0
trap 'exit 130' 1 2 15

require_runtime() {
    [ "$(firmware_version)" = "${EXPECTED_FIRMWARE}" ] || \
        die "firmware_mismatch_expected_${EXPECTED_FIRMWARE}"
    grep -q ' /mnt/us ' /proc/mounts || die "userstore_not_mounted"
    [ "$(path_kind "${TARGET}")" = file ] || die "target_not_regular_file"
    for command_name in awk chmod cp grep head mkdir mv rm rmdir sed sha256sum sync; do
        command -v "${command_name}" >/dev/null 2>&1 || \
            die "missing_command_${command_name}"
    done
}

source_state() {
    [ "$(path_kind "${TARGET}")" = file ] || {
        say unsafe_target_type
        return 0
    }
    target_hash="$(file_sha256 "${TARGET}")"
    if [ "${target_hash}" = "${ORIGINAL_SHA256}" ]; then
        say original
    elif [ "${target_hash}" = "${PATCHED_SHA256}" ]; then
        say patched
    else
        say foreign
    fi
}

rollback_state() {
    dir_kind="$(path_kind "${ROLLBACK_DIR}")"
    rollback_kind="$(path_kind "${ROLLBACK}")"
    stage_kind="$(path_kind "${ROLLBACK_STAGE}")"
    if [ "${dir_kind}" = absent ] && [ "${rollback_kind}" = absent ]; then
        say absent
    elif [ "${dir_kind}" != directory ]; then
        say unsafe_directory
    else
        for entry in \
            "${ROLLBACK_DIR}"/* \
            "${ROLLBACK_DIR}"/.[!.]* \
            "${ROLLBACK_DIR}"/..?*; do
            if [ -e "${entry}" ] || [ -L "${entry}" ]; then
                case "${entry}" in
                    "${ROLLBACK}"|"${ROLLBACK_STAGE}") ;;
                    *) say unsafe_directory_contents; return 0 ;;
                esac
            fi
        done

        case "${rollback_kind}:${stage_kind}" in
            absent:absent)
                say empty_directory
                ;;
            file:absent)
                if [ "$(file_sha256 "${ROLLBACK}")" = "${ORIGINAL_SHA256}" ]; then
                    say original
                else
                    say foreign
                fi
                ;;
            absent:file)
                if [ "$(file_sha256 "${ROLLBACK_STAGE}")" = "${ORIGINAL_SHA256}" ]; then
                    say staged_original
                else
                    say staged_partial
                fi
                ;;
            file:file)
                say unsafe_multiple_owned_entries
                ;;
            absent:*)
                say "unsafe_stage_${stage_kind}"
                ;;
            *:absent)
                say "unsafe_rollback_${rollback_kind}"
                ;;
            *)
                say unsafe_rollback_topology
                ;;
        esac
    fi
}

print_status() {
    firmware="$(firmware_version)"
    current_source_state="$(source_state)"
    current_rollback_state="$(rollback_state)"
    say "firmware=${firmware:-unknown}"
    say "source=${current_source_state}"
    say "rollback=${current_rollback_state}"
    case "${current_source_state}:${current_rollback_state}" in
        original:absent)
            say "stability_guard=not_installed"
            ;;
        original:original)
            say "stability_guard=install_interrupted_safe_to_resume"
            ;;
        original:empty_directory|original:staged_original|original:staged_partial)
            say "stability_guard=install_interrupted_safe_to_resume"
            ;;
        patched:original)
            say "stability_guard=installed_next_launch"
            ;;
        *)
            say "stability_guard=unsafe_or_foreign"
            ;;
    esac
}

ensure_rollback() {
    while :; do
        current_rollback_state="$(rollback_state)"
        case "${current_rollback_state}" in
            original)
                return 0
                ;;
            absent)
                mkdir "${ROLLBACK_DIR}" || die "rollback_directory_create_failed"
                sync
                [ "$(rollback_state)" = empty_directory ] || \
                    die "rollback_directory_state_not_durable"
                ;;
            empty_directory)
                ROLLBACK_TMP="${ROLLBACK_STAGE}"
                [ "$(path_kind "${ROLLBACK_TMP}")" = absent ] || \
                    die "rollback_stage_path_exists"
                cp "${TARGET}" "${ROLLBACK_TMP}" || die "rollback_copy_failed"
                [ "$(file_sha256 "${ROLLBACK_TMP}")" = "${ORIGINAL_SHA256}" ] || \
                    die "rollback_stage_hash_mismatch"
                chmod 0600 "${ROLLBACK_TMP}" || die "rollback_chmod_failed"
                sync
                [ "$(rollback_state)" = staged_original ] || \
                    die "rollback_stage_not_durable"
                ;;
            staged_partial)
                # This fixed path is manager-owned. It can only precede target
                # publication, so it is safe to discard while the target is
                # still the exact original and retry the copy.
                [ "$(source_state)" = original ] || \
                    die "partial_stage_with_nonoriginal_source"
                rm -f "${ROLLBACK_STAGE}" || die "partial_stage_remove_failed"
                sync
                [ "$(rollback_state)" = empty_directory ] || \
                    die "partial_stage_cleanup_not_durable"
                ;;
            staged_original)
                [ "$(source_state)" = original ] || \
                    die "staged_rollback_with_nonoriginal_source"
                [ "$(path_kind "${ROLLBACK}")" = absent ] || \
                    die "rollback_path_appeared"
                mv "${ROLLBACK_STAGE}" "${ROLLBACK}" || \
                    die "rollback_publish_failed"
                ROLLBACK_TMP=""
                sync
                [ "$(rollback_state)" = original ] || \
                    die "rollback_publish_not_durable"
                ;;
            *)
                die "rollback_state_refused_${current_rollback_state}"
                ;;
        esac
    done
}

finish_rollback_cleanup() {
    current_rollback_state="$(rollback_state)"
    case "${current_rollback_state}" in
        original)
            rm -f "${ROLLBACK}" || die "rollback_remove_failed_after_restore"
            sync
            [ "$(rollback_state)" = empty_directory ] || \
                die "rollback_removal_not_durable"
            ;;
        staged_original|staged_partial)
            # Cancels an interrupted install before target publication.
            rm -f "${ROLLBACK_STAGE}" || die "rollback_stage_remove_failed"
            sync
            [ "$(rollback_state)" = empty_directory ] || \
                die "rollback_stage_removal_not_durable"
            ;;
        empty_directory) ;;
        absent) return 0 ;;
        *) die "rollback_cleanup_state_refused_${current_rollback_state}" ;;
    esac

    rmdir "${ROLLBACK_DIR}" || die "rollback_directory_not_exactly_empty"
    sync
    [ "$(rollback_state)" = absent ] || \
        die "rollback_directory_removal_not_durable"
}

write_patched_candidate() {
    TARGET_TMP="${TARGET}.lazying-art.$$"
    [ "$(path_kind "${TARGET_TMP}")" = absent ] || die "target_temp_path_exists"
    awk '
        {
            print
            if ($0 == "function Contact:isTwoFingerTap(buddy_contact)") {
                matches++
                print "    if not self.current_tev or not self.initial_tev or"
                print "       not buddy_contact or not buddy_contact.current_tev or not buddy_contact.initial_tev then"
                print "        logger.warn(\"Contact:isTwoFingerTap ignored incomplete contact state\")"
                print "        return false"
                print "    end"
                print ""
            }
        }
        END {
            if (matches != 1) exit 42
        }
    ' "${TARGET}" >"${TARGET_TMP}" || die "patch_generation_failed"
    [ "$(file_sha256 "${TARGET_TMP}")" = "${PATCHED_SHA256}" ] || \
        die "patched_candidate_hash_mismatch"
    chmod 0777 "${TARGET_TMP}" || die "patched_candidate_chmod_failed"
}

install_guard() {
    require_runtime
    current_source_state="$(source_state)"
    case "${current_source_state}" in
        patched)
            [ "$(rollback_state)" = original ] || die "patched_target_without_exact_rollback"
            say "result=already_installed_next_launch"
            print_status
            return 0
            ;;
        original) ;;
        *) die "source_state_refused_${current_source_state}" ;;
    esac

    ensure_rollback
    [ "$(source_state)" = original ] || die "source_changed_after_rollback"
    write_patched_candidate
    [ "$(source_state)" = original ] || die "source_changed_before_publish"
    mv -f "${TARGET_TMP}" "${TARGET}" || die "patched_publish_failed"
    TARGET_TMP=""
    sync
    [ "$(source_state)" = patched ] || die "patched_publish_not_durable"
    say "result=installed_for_next_koreader_launch"
    print_status
}

uninstall_guard() {
    require_runtime
    current_source_state="$(source_state)"
    current_rollback_state="$(rollback_state)"
    case "${current_source_state}:${current_rollback_state}" in
        patched:original)
            TARGET_TMP="${TARGET}.lazying-art.$$"
            [ "$(path_kind "${TARGET_TMP}")" = absent ] || \
                die "target_temp_path_exists"
            cp "${ROLLBACK}" "${TARGET_TMP}" || die "restore_copy_failed"
            [ "$(file_sha256 "${TARGET_TMP}")" = "${ORIGINAL_SHA256}" ] || \
                die "restore_temp_hash_mismatch"
            chmod 0777 "${TARGET_TMP}" || die "restore_temp_chmod_failed"
            [ "$(source_state)" = patched ] || die "source_changed_before_restore"
            mv -f "${TARGET_TMP}" "${TARGET}" || die "restore_publish_failed"
            TARGET_TMP=""
            sync
            [ "$(source_state)" = original ] || die "restore_not_durable"
            ;;
        original:original|original:empty_directory|original:staged_original|original:staged_partial)
            # Resume a prior restore/cleanup or cancel an interrupted install.
            ;;
        original:absent)
            say "result=already_uninstalled_original"
            print_status
            return 0
            ;;
        *)
            die "uninstall_state_refused_${current_source_state}_${current_rollback_state}"
            ;;
    esac

    [ "$(source_state)" = original ] || die "original_source_required_for_cleanup"
    finish_rollback_cleanup
    [ "$(source_state):$(rollback_state)" = original:absent ] || \
        die "uninstall_final_state_not_exact"
    say "result=uninstalled_original_restored"
    print_status
}

usage() {
    say "usage: $0 status|audit|install|uninstall"
}

action="${1:-status}"
case "${action}" in
    status)
        print_status
        ;;
    audit)
        require_runtime
        case "$(source_state):$(rollback_state)" in
            original:absent|original:empty_directory|original:staged_original|\
            original:staged_partial|original:original|patched:original) ;;
            *) die "unsafe_or_foreign_stability_state" ;;
        esac
        say "result=audit_passed"
        print_status
        ;;
    install)
        install_guard
        ;;
    uninstall)
        uninstall_guard
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
