#!/usr/bin/env bash
# Application-owned snapshot of a named Bash coprocess. Source, do not execute.
# Never signal a PID: the child has a finite outer timeout and accepts a stop
# request through its duplicated stdin. Bash may unset CANARY_PID/CANARY[] on exit.
canary_capture() {
  CANARY_OWNER_PID=${CANARY_PID-}
  CANARY_READ_FD=''
  CANARY_WRITE_FD=''
  local read_fd=${CANARY[0]-} write_fd=${CANARY[1]-}
  [[ $CANARY_OWNER_PID =~ ^[0-9]+$ && $read_fd =~ ^[0-9]+$ && $write_fd =~ ^[0-9]+$ ]] || return 2
  exec {CANARY_READ_FD}<&"$read_fd" || return 2
  exec {CANARY_WRITE_FD}>&"$write_fd" || return 2
}

canary_read() {
  local name=$1 seconds=$2
  [[ ${CANARY_READ_FD-} =~ ^[0-9]+$ ]] || return 2
  read -r -t "$seconds" -u "$CANARY_READ_FD" "$name"
}

canary_is_live() {
  [[ ${CANARY_OWNER_PID-} =~ ^[0-9]+$ ]] || return 1
  jobs -pr | grep -Fxq -- "$CANARY_OWNER_PID"
}

canary_stop() {
  # No kill/kill -0 on a stale numeric PID. Even after fast child exit, wait
  # only on the captured shell child; never substitute a coprocess special.
  if [[ ${CANARY_WRITE_FD-} =~ ^[0-9]+$ ]]; then
    (trap '' PIPE; printf 'STOP %s\n' "${TOKEN-}" >&"$CANARY_WRITE_FD") 2>/dev/null || true
    exec {CANARY_WRITE_FD}>&- || true
  fi
  if [[ ${CANARY_READ_FD-} =~ ^[0-9]+$ ]]; then
    exec {CANARY_READ_FD}<&- || true
  fi
  if [[ ${CANARY_OWNER_PID-} =~ ^[0-9]+$ ]]; then
    wait "$CANARY_OWNER_PID" 2>/dev/null || true
    canary_is_live && return 1
  fi
  return 0
}
