package com.github.malikovpro.dt.bsl.syntaxhelp.export;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
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
