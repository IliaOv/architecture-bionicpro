package ru.bionicpro.keycloak.yandex;

import com.fasterxml.jackson.databind.JsonNode;
import org.keycloak.broker.oidc.AbstractOAuth2IdentityProvider;
import org.keycloak.broker.oidc.OAuth2IdentityProviderConfig;
import org.keycloak.broker.provider.BrokeredIdentityContext;
import org.keycloak.broker.provider.IdentityBrokerException;
import org.keycloak.broker.provider.util.SimpleHttp;
import org.keycloak.broker.social.SocialIdentityProvider;
import org.keycloak.events.EventBuilder;
import org.keycloak.models.KeycloakSession;

/**
 * Яндекс ID как чистый OAuth 2.0 (без scope openid).
 * Стандартный OIDC-брокер Keycloak всегда добавляет openid → Yandex отвечает invalid_scope.
 */
public class YandexIdentityProvider
        extends AbstractOAuth2IdentityProvider<OAuth2IdentityProviderConfig>
        implements SocialIdentityProvider<OAuth2IdentityProviderConfig> {

    public static final String AUTH_URL = "https://oauth.yandex.ru/authorize";
    public static final String TOKEN_URL = "https://oauth.yandex.ru/token";
    public static final String USER_INFO_URL = "https://login.yandex.ru/info?format=json";
    public static final String DEFAULT_SCOPE = "login:info login:email login:avatar";

    public YandexIdentityProvider(KeycloakSession session, OAuth2IdentityProviderConfig config) {
        super(session, config);
        config.setAuthorizationUrl(AUTH_URL);
        config.setTokenUrl(TOKEN_URL);
        config.setUserInfoUrl(USER_INFO_URL);
    }

    @Override
    protected String getDefaultScopes() {
        return DEFAULT_SCOPE;
    }

    @Override
    protected boolean supportsExternalExchange() {
        return true;
    }

    @Override
    protected String getProfileEndpointForValidation(EventBuilder event) {
        return USER_INFO_URL;
    }

    @Override
    protected BrokeredIdentityContext extractIdentityFromProfile(EventBuilder event, JsonNode profile) {
        String id = getJsonProperty(profile, "id");
        if (id == null || id.isBlank()) {
            throw new IdentityBrokerException("Yandex profile without id");
        }

        BrokeredIdentityContext user = new BrokeredIdentityContext(id);
        user.setIdpConfig(getConfig());
        user.setIdp(this);

        String login = getJsonProperty(profile, "login");
        user.setUsername(login != null ? login : id);

        String email = getJsonProperty(profile, "default_email");
        if (email == null) {
            email = getJsonProperty(profile, "emails");
        }
        user.setEmail(email);

        String firstName = getJsonProperty(profile, "first_name");
        String lastName = getJsonProperty(profile, "last_name");
        if (firstName == null) {
            firstName = getJsonProperty(profile, "real_name");
        }
        user.setFirstName(firstName);
        user.setLastName(lastName);

        user.setUserAttribute("yandex_id", id);
        if (login != null) {
            user.setUserAttribute("yandex_login", login);
        }
        return user;
    }

    @Override
    protected BrokeredIdentityContext doGetFederatedIdentity(String accessToken) {
        try {
            // Яндекс требует заголовок Authorization: OAuth <token>, не Bearer.
            JsonNode profile = SimpleHttp.doGet(USER_INFO_URL, session)
                    .header("Authorization", "OAuth " + accessToken)
                    .asJson();
            return extractIdentityFromProfile(null, profile);
        } catch (Exception e) {
            throw new IdentityBrokerException("Could not obtain user profile from Yandex", e);
        }
    }
}
