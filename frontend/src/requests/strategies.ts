import { Strategy } from "./base";
import { TargetSource } from "./types";

/**
 * Default authentication strategy using session-based auth
 */
export class DefaultStrategy extends Strategy {
    constructor() {
        super({
            authType:"session",
            targetSource: TargetSource.INSOURCE,
            token: "",
            authKey: undefined,
            authValue: undefined
        });
    }

    applyHeaders(headers: Record<string, string>): Record<string, string> {
        return {
            ...headers,
        };
    }
}
/**
 * JWT authentication strategy
 * Automatically adds 'Authorization: Bearer <token>' header to requests
 */
export class JWTStrategy extends Strategy {
    constructor(token: string|(() => string)) {
        super({
            authType:"jwt",
            targetSource: TargetSource.INSOURCE,
            token: token,
            authKey: "Authorization",
            authValue: "Bearer"
        });
    }
    applyHeaders(headers: Record<string, string>): Record<string, string> {
        const token = typeof this.authOptions.token === "function" ? this.authOptions.token() : this.authOptions.token;
        if (token){
            headers[this.authOptions.authKey!]= `${this.authOptions.authValue} ${token}`;
        }
        return headers;
    }   
}

