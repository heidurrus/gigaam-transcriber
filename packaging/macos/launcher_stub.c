/*
 * Native CFBundleExecutable of the macOS app (spec FR-PLAT-01 AC2, FR-PLAT-06 AC2).
 *
 * It replaces itself (execv, same process) with the bundled Python running
 * boot.py. Keeping one process launched by LaunchServices means macOS shows
 * the app's own name in the Dock and in Microphone / Screen Recording
 * permission prompts, instead of "python" or Terminal.
 *
 * Layout:  X.app/Contents/MacOS/<this>
 *          X.app/Contents/Resources/python/bin/python3
 *          X.app/Contents/Resources/app/boot.py
 */
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    char exe[PATH_MAX], real[PATH_MAX], contents[PATH_MAX];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0 || realpath(exe, real) == NULL) {
        fprintf(stderr, "launcher: cannot resolve executable path\n");
        return 1;
    }
    /* real = .../Contents/MacOS/<name>  →  contents = .../Contents */
    strncpy(contents, real, sizeof(contents) - 1);
    contents[sizeof(contents) - 1] = '\0';
    for (int up = 0; up < 2; up++) {
        char *slash = strrchr(contents, '/');
        if (slash == NULL || slash == contents) {
            fprintf(stderr, "launcher: unexpected bundle layout: %s\n", real);
            return 1;
        }
        *slash = '\0';
    }

    char python[PATH_MAX], script[PATH_MAX];
    snprintf(python, sizeof(python), "%s/Resources/python/bin/python3", contents);
    snprintf(script, sizeof(script), "%s/Resources/app/boot.py", contents);

    /* Finder passes -psn_* on old systems; drop it. Forward everything else. */
    char **args = calloc((size_t)argc + 3, sizeof(char *));
    int n = 0;
    args[n++] = python;
    args[n++] = script;
    for (int i = 1; i < argc; i++) {
        if (strncmp(argv[i], "-psn_", 5) != 0) args[n++] = argv[i];
    }
    args[n] = NULL;

    execv(python, args);
    perror("launcher: execv python");
    return 1;
}
