"""Microphone permission on macOS (spec FR-PLAT-02 AC2/AC3).

Asks through AVFoundation, so macOS shows its standard prompt for the app, and
reports a denied permission with where to turn it on, instead of recording
nothing. Only meaningful when running as the app (see packaging/macos/
launcher_stub.c): a plain python process has no usage description to prompt with.
"""
import sys
import threading

# AVAuthorizationStatus
NOT_DETERMINED, RESTRICTED, DENIED, AUTHORIZED = 0, 1, 2, 3

DENIED_MESSAGE = ("microphone access is off for Requirements Workbench. Turn it on in "
                  "System Settings → Privacy & Security → Microphone, then record again")


def microphone_access(timeout=120, av=None):
    """(allowed, reason). Shows the macOS prompt the first time; blocks until answered."""
    if sys.platform != "darwin":
        return True, None
    if av is None:
        try:
            import AVFoundation as av
        except ImportError:
            return True, None   # can't check; let the recording itself report problems
    status = av.AVCaptureDevice.authorizationStatusForMediaType_(av.AVMediaTypeAudio)
    if status == AUTHORIZED:
        return True, None
    if status in (DENIED, RESTRICTED):
        return False, DENIED_MESSAGE
    answered, result = threading.Event(), {}

    def done(granted):
        result["granted"] = bool(granted)
        answered.set()

    av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(av.AVMediaTypeAudio, done)
    if not answered.wait(timeout):
        return False, "the microphone permission prompt wasn't answered"
    return (True, None) if result["granted"] else (False, DENIED_MESSAGE)
