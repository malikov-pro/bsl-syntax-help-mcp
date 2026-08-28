package com.github.malikovpro.dt.bsl.syntaxhelp.export;

import java.util.List;

import com._1c.g5.v8.dt.platform.version.Version;

public final class Layers {
    public static final String BASE = "base";
    public static final List<String> ALL = List.of(BASE, "8.3.25", "8.3.26", "8.3.27", "8.5.1");

    private Layers() {
    }

    public static Version versionFor(String layer) {
	if (BASE.equals(layer)) {
	    return Version.V8_3_24;
	}
	return Version.create(layer);
    }
}
