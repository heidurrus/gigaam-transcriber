/*
 * Native CFBundleExecutable of the macOS app (spec FR-PLAT-01 AC2, FR-PLAT-02 AC2).
 *
 * Runs the bundled Python *inside this process* (libpython + Py_BytesMain)
 * instead of exec-ing the python binary. macOS privacy (TCC) judges a process
 * by the code it is running: after an exec the process was "python3.12" with
 * no Info.plist, so microphone access was silently denied without a prompt.
 * Embedded, the process stays the signed app with its usage descriptions, and
 * prompts show "Requirements Workbench".
 *
 * Layout:  X.app/Contents/MacOS/<this>
 *          X.app/Contents/Resources/python/lib/libpython3.12.dylib
 *          X.app/Contents/Resources/app/boot.py
 */
#include <dlfcn.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef PY_LIB
#define PY_LIB "libpython3.12.dylib"
#endif

typedef int (*py_bytes_main_t)(int, char **);

int main(int argc, char *argv[]) {
    char exe[PATH_MAX], real[PATH_MAX], contents[PATH_MAX];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0 || realpath(exe, real) == NULL) {
        fprintf(stderr, "launcher: cannot resolve executable path\n");
        return 1;
    }
    /* real = .../Contents/MacOS/<name>  ->  contents = .../Contents */
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

    char home[PATH_MAX], lib[PATH_MAX], script[PATH_MAX];
    snprintf(home, sizeof(home), "%s/Resources/python", contents);
    snprintf(lib, sizeof(lib), "%s/lib/" PY_LIB, home);
    snprintf(script, sizeof(script), "%s/Resources/app/boot.py", contents);

    /* The bundled runtime, not whatever Python the user has installed. */
    setenv("PYTHONHOME", home, 1);
    unsetenv("PYTHONPATH");
    setenv("PYTHONNOUSERSITE", "1", 1);
    setenv("WORKBENCH_EMBEDDED", "1", 1);  /* boot.py: stay in this process */

    void *handle = dlopen(lib, RTLD_NOW | RTLD_GLOBAL);
    if (handle == NULL) {
        fprintf(stderr, "launcher: cannot load %s: %s\n", lib, dlerror());
        return 1;
    }
    py_bytes_main_t py_main = (py_bytes_main_t)dlsym(handle, "Py_BytesMain");
    if (py_main == NULL) {
        fprintf(stderr, "launcher: Py_BytesMain missing in %s\n", lib);
        return 1;
    }

    /* python <boot.py> [args…]; Finder's old -psn_* argument is dropped. */
    char **args = calloc((size_t)argc + 3, sizeof(char *));
    int n = 0;
    args[n++] = real;
    args[n++] = script;
    for (int i = 1; i < argc; i++) {
        if (strncmp(argv[i], "-psn_", 5) != 0) args[n++] = argv[i];
    }
    args[n] = NULL;
    return py_main(n, args);
}
