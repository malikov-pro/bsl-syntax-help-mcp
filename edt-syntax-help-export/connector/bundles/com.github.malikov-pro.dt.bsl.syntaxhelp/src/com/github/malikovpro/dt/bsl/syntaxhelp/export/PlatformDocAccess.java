package com.github.malikovpro.dt.bsl.syntaxhelp.export;

import org.eclipse.core.runtime.Platform;
import org.osgi.framework.Bundle;

import com._1c.g5.v8.dt.platform.doc.PlatformDocProvider;
import com.github.malikovpro.dt.bsl.syntaxhelp.SyntaxHelpPlugin;
import com.google.inject.Injector;

/**
 * Resolves {@link PlatformDocProvider} through the BSL UI Guice injector.
 * The activator package is not exported, so the class is loaded via the bundle.
 */
public final class PlatformDocAccess {
    private static final String BSL_UI_BUNDLE = "com._1c.g5.v8.dt.bsl.ui";
    private static final String BSL_ACTIVATOR = "com._1c.g5.v8.dt.bsl.ui.internal.BslActivator";
    private static final String BSL_LANGUAGE_ID = "com._1c.g5.v8.dt.bsl.Bsl";

    private static PlatformDocProvider provider;
    private static boolean resolved;

    private PlatformDocAccess() {
    }

    public static synchronized PlatformDocProvider getProvider() {
	if (resolved) {
	    return provider;
	}
	try {
	    Bundle bundle = Platform.getBundle(BSL_UI_BUNDLE);
	    if (bundle == null) {
		SyntaxHelpPlugin.logWarning("BSL UI bundle is not installed; syntax helper unavailable");
		return null;
	    }
	    Class<?> activatorClass = bundle.loadClass(BSL_ACTIVATOR);
	    Object activator = activatorClass.getMethod("getInstance").invoke(null);
	    if (activator == null) {
		SyntaxHelpPlugin.logWarning("BSL UI plugin is not started yet; retry later");
		return null;
	    }
	    Object injector = activatorClass.getMethod("getInjector", String.class).invoke(activator,
		    BSL_LANGUAGE_ID);
	    if (injector instanceof Injector) {
		provider = ((Injector) injector).getInstance(PlatformDocProvider.class);
	    } else {
		SyntaxHelpPlugin.logWarning("BSL injector is not a com.google.inject.Injector visible here");
	    }
	} catch (Exception | LinkageError e) {
	    SyntaxHelpPlugin.logError("Cannot resolve PlatformDocProvider", e);
	    resolved = true;
	    return provider;
	}
	resolved = true;
	return provider;
    }
}
