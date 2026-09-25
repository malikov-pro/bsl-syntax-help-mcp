package com.github.malikovpro.dt.bsl.syntaxhelp.export;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

public final class IngestClient {
	private final HttpClient http = HttpClient.newBuilder()
		.version(HttpClient.Version.HTTP_1_1)
		.connectTimeout(Duration.ofSeconds(15))
		.build();
    private final String baseUrl;
    private final String token;

    public IngestClient(String baseUrl, String token) {
	this.baseUrl = trimSlash(baseUrl);
	this.token = token == null ? "" : token;
    }

    /** Базовый URL без завершающего слэша — для сообщений пользователю. */
    public String url() {
	return baseUrl;
    }

    public String begin(String layer) throws IOException, InterruptedException {
	var body = new JsonObject();
	body.addProperty("layer", layer);
	var json = post("/ingest/begin", body.toString(), Duration.ofSeconds(30));
	return json.get("session_id").getAsString();
    }

    public JsonObject sendBatch(String sessionId, List<DocCard> cards) throws IOException, InterruptedException {
	var body = new JsonObject();
	body.addProperty("session_id", sessionId);
	var array = new JsonArray();
	for (var card : cards) {
	    array.add(card.toJson());
	}
	body.add("cards", array);
	return post("/ingest/batches", body.toString(), Duration.ofMinutes(2));
    }

    public JsonObject commit(String sessionId) throws IOException, InterruptedException {
	var body = new JsonObject();
	body.addProperty("session_id", sessionId);
	return post("/ingest/commit", body.toString(), Duration.ofMinutes(10));
    }

    public void abort(String sessionId) {
	if (sessionId == null || sessionId.isBlank()) {
	    return;
	}
	try {
	    var body = new JsonObject();
	    body.addProperty("session_id", sessionId);
	    post("/ingest/abort", body.toString(), Duration.ofSeconds(30));
	} catch (Exception e) {
	    // best-effort; the session TTL will drop it
	}
    }

    public String status() throws IOException, InterruptedException {
	var request = authorized(HttpRequest.newBuilder(URI.create(baseUrl + "/status")).GET()
		.timeout(Duration.ofSeconds(20)));
	var response = http.send(request, HttpResponse.BodyHandlers.ofString());
	requireOk(response, "/status");
	return response.body();
    }

    /**
     * Лёгкая проверка достижимости контейнера перед длинной выгрузкой.
     * Любой HTTP-ответ (даже 503 «starting») означает «доступен»: падаем
     * только на сетевых ошибках. Токен не нужен — /status открытый.
     */
    public void ping() throws IOException, InterruptedException {
	var request = HttpRequest.newBuilder(URI.create(baseUrl + "/status")).GET()
		.timeout(Duration.ofSeconds(10)).build();
	http.send(request, HttpResponse.BodyHandlers.discarding());
    }

    /**
     * Понятный пользователю текст вместо <code>e.getMessage()</code>, который у
     * сетевых исключений бывает null («Статус:null») или слишком техническим.
     */
    public String describe(Throwable failure) {
	var cause = failure;
	for (var depth = 0; cause.getCause() != null && cause.getCause() != cause && depth < 8; depth++) {
	    cause = cause.getCause();
	}
	if (cause instanceof java.net.ConnectException) {
	    return "MCP-контейнер недоступен по адресу " + baseUrl + " (соединение отклонено)."
		    + " Запустите контейнер: docker compose -f docker/mcp/docker-compose.yml up -d"
		    + " — и проверьте URL и порт.";
	}
	if (cause instanceof java.net.http.HttpTimeoutException) {
	    return "MCP-контейнер не отвечает по адресу " + baseUrl + " (истёк таймаут)."
		    + " Проверьте, что контейнер запущен и не занят долгой операцией.";
	}
	if (cause instanceof java.net.UnknownHostException) {
	    return "Не удалось определить адрес «" + cause.getMessage() + "». Проверьте URL контейнера.";
	}
	if (cause instanceof javax.net.ssl.SSLException) {
	    return "Ошибка TLS при обращении к " + baseUrl + " (" + cause.getMessage() + ")."
		    + " MCP слушает http, а не https.";
	}
	var message = chainText(failure);
	if (failure instanceof IllegalArgumentException) {
	    return "Некорректный URL «" + baseUrl + "»: " + message;
	}
	if (message != null && message.contains("HTTP 401")) {
	    return message + " — проверьте INGEST_TOKEN (он нужен для «Выгрузить» и «Очистить»).";
	}
	return message != null ? message
		: failure.getClass().getSimpleName()
			+ (cause.getMessage() == null || cause.getMessage().isBlank() ? ""
				: ": " + cause.getMessage());
    }

    /** Ответ /status в виде короткой человекочитаемой сводки; если тело не
     *  статус-JSON (прокси, страница ошибки) — возвращается как есть. */
    public String formatStatus(String body) {
	if (body == null || body.isBlank()) {
	    return "Пустой ответ.";
	}
	try {
	    var root = JsonParser.parseString(body).getAsJsonObject();
	    var lines = new ArrayList<String>();
	    lines.add("Состояние: " + value(root, "status"));
	    var layers = root.getAsJsonArray("layers");
	    if (layers != null && !layers.isEmpty()) {
		var names = new ArrayList<String>();
		layers.forEach(layer -> names.add(layer.getAsString()));
		lines.add("Слои: " + String.join(", ", names));
	    } else {
		lines.add("Слои: нет (база пуста — выполните «Выгрузить»)");
	    }
	    lines.add("Документы: " + value(root, "documents") + ", чанки: " + value(root, "chunks"));
	    var queue = root.getAsJsonObject("embed_queue");
	    if (queue != null) {
		lines.add("Очередь эмбеддингов: готово " + value(queue, "done") + ", в ожидании "
			+ value(queue, "pending") + ", ошибки " + value(queue, "error"));
	    }
	    var dependencies = root.getAsJsonObject("dependencies");
	    var embedder = dependencies == null ? null : dependencies.getAsJsonObject("embedder");
	    if (embedder != null) {
		lines.add("Эмбеддер: " + value(embedder, "status") + " (" + value(embedder, "model") + ")");
	    }
	    return String.join("\n", lines);
	} catch (Exception e) {
	    return body;
	}
    }

    private static String value(JsonObject object, String key) {
	var item = object.get(key);
	return item == null || item.isJsonNull() ? "—" : item.getAsString();
    }

    private static String chainText(Throwable failure) {
	var parts = new ArrayList<String>();
	for (var current = failure; current != null && parts.size() < 8; current = current.getCause()) {
	    var message = current.getMessage();
	    if (message != null && !message.isBlank()) {
		parts.add(current.getClass().getSimpleName() + ": " + message.strip());
	    }
	    if (current.getCause() == current) {
		break;
	    }
	}
	return parts.isEmpty() ? null : String.join("; ", parts);
    }


    public String deleteLayer(String layer) throws IOException, InterruptedException {
	var request = authorized(HttpRequest.newBuilder(URI.create(baseUrl + "/admin/layers/" + layer))
		.method("DELETE", HttpRequest.BodyPublishers.noBody()).timeout(Duration.ofMinutes(2)));
	var response = http.send(request, HttpResponse.BodyHandlers.ofString());
	requireOk(response, "/admin/layers/" + layer);
	return response.body();
    }

    public String wipeDatabase() throws IOException, InterruptedException {
	var request = authorized(HttpRequest.newBuilder(URI.create(baseUrl + "/admin/database"))
		.method("DELETE", HttpRequest.BodyPublishers.ofString("{\"confirm\":true}"))
		.header("Content-Type", "application/json").timeout(Duration.ofMinutes(2)));
	var response = http.send(request, HttpResponse.BodyHandlers.ofString());
	requireOk(response, "/admin/database");
	return response.body();
    }

    private JsonObject post(String path, String json, Duration timeout) throws IOException, InterruptedException {
	var request = authorized(HttpRequest.newBuilder(URI.create(baseUrl + path))
		.timeout(timeout)
		.header("Content-Type", "application/json")
		.POST(HttpRequest.BodyPublishers.ofString(json)));
	var response = http.send(request, HttpResponse.BodyHandlers.ofString());
	requireOk(response, path);
	return JsonParser.parseString(response.body()).getAsJsonObject();
    }

    private HttpRequest authorized(HttpRequest.Builder builder) {
	if (!token.isBlank()) {
	    builder.header("Authorization", "Bearer " + token);
	}
	return builder.build();
    }

    private static void requireOk(HttpResponse<String> response, String path) throws IOException {
	var code = response.statusCode();
	if (code < 200 || code >= 300) {
	    var body = response.body();
	    if (body != null && body.length() > 500) {
		body = body.substring(0, 500);
	    }
	    throw new IOException(path + " HTTP " + code + (body == null || body.isBlank() ? "" : ": " + body));
	}
    }

    private static String trimSlash(String url) {
	if (url == null) {
	    return "";
	}
	var trimmed = url.trim();
	while (trimmed.endsWith("/")) {
	    trimmed = trimmed.substring(0, trimmed.length() - 1);
	}
	return trimmed;
    }
}
