package com.github.malikovpro.dt.bsl.syntaxhelp.export;

import org.eclipse.core.runtime.Platform;
import org.osgi.framework.Bundle;

import com._1c.g5.v8.dt.platform.doc.PlatformDocProvider;
import com.github.malikovpro.dt.bsl.syntaxhelp.SyntaxHelpPlugin;

/**
 * Resolves {@link PlatformDocProvider} through the BSL UI Guice injector.
 * The activator package is not exported, so the class is loaded via the bundle.
 *
 * <p>Resolution is attempted on every call and a failed attempt is never
 * latched: the BSL UI plugin starts lazily (first BSL editor or first class
 * load), and an early failure — plugin not started yet, provider not
 * provisionable yet — fixes itself later. Latching the failure here made the
 * «Откройте BSL-редактор и повторите» advice impossible to satisfy (issue #3).
 */
public final class PlatformDocAccess {
    private static final String BSL_UI_BUNDLE = "com._1c.g5.v8.dt.bsl.ui";
    private static final String BSL_ACTIVATOR = "com._1c.g5.v8.dt.bsl.ui.internal.BslActivator";
    private static final String BSL_LANGUAGE_ID = "com._1c.g5.v8.dt.bsl.Bsl";

    private static PlatformDocProvider provider;

    private PlatformDocAccess() {
    }

    public static synchronized PlatformDocProvider getProvider() {
	if (provider != null) {
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
	    if (injector == null) {
		SyntaxHelpPlugin.logWarning("BSL injector for " + BSL_LANGUAGE_ID
			+ " is not registered yet; open a BSL editor and retry");
		return null;
	    }
	    // com.google.inject в EDT экспортируют несколько бандлов (7.0.0 и 7.0.2):
	    // bsl.ui берёт свою копию через Require-Bundle, а наш Import-Package
	    // может завестись на другую — тогда instanceof и типизированный вызов
	    // ломаются («injector is not visible here»). Поэтому getInstance(Class)
	    // зовётся рефлексивно: работает с любой копией Guice, а класс
	    // PlatformDocProvider у обеих сторон общий (экспортёр пакета один).
	    //
	    // Метод ищем на ЭКСПОРТИРУЕМОМ интерфейсе com.google.inject.Injector:
	    // getMethod на классе-реализации возвращает объявление в
	    // com.google.inject.internal.InjectorImpl (пакет не экспортирован), и
	    // invoke из чужого бандла даёт IllegalAccessException.
	    provider = (PlatformDocProvider) getInstance(injector, PlatformDocProvider.class);
	} catch (Exception | LinkageError e) {
	    SyntaxHelpPlugin.logError("Cannot resolve PlatformDocProvider", e);
	}
	return provider;
    }

    /**
     * Вызов {@code Injector.getInstance(Class)} без зависимости от конкретной
     * копии Guice. Метод берётся с экспортируемого интерфейса
     * {@code com.google.inject.Injector}, найденного в иерархии типов
     * инжектора, — объявление в неэкспортированном
     * {@code com.google.inject.internal.InjectorImpl} недоступно чужому бандлу.
     * Если интерфейса в иерархии нет (нестандартная обёртка), остаётся фолбэк
     * через {@code setAccessible(true)}.
     */
    private static Object getInstance(Object injector, Class<?> type) throws Exception {
	for (var t = injector.getClass(); t != null; t = t.getSuperclass()) {
	    for (var iface : t.getInterfaces()) {
		if ("com.google.inject.Injector".equals(iface.getName())) {
		    return iface.getMethod("getInstance", Class.class).invoke(injector, type);
		}
	    }
	}
	var method = injector.getClass().getMethod("getInstance", Class.class);
	method.setAccessible(true);
	return method.invoke(injector, type);
    }
}
