import  { 
    type AuthOptions , 
    Strategy as StrategyInterface , 
    RequestsOptions , 
    InterceptorType , 
    RequestProps ,
    Methods
} from "./types";
import { InterceptorManager } from "./interceptor";
import { DefaultStrategy } from "./strategies";

/**
 * Base strategy class for authentication
 * Extend this class to implement custom authentication strategies
 */
export class Strategy implements StrategyInterface {
    authOptions: AuthOptions;
    constructor(authOptions: AuthOptions) {
        this.authOptions = authOptions;
    }
    applyHeaders(headers: Record<string, string>): Record<string, string> {
        return headers   
    }   
}


/**
 * Base request class with common functionality for all request types
 */
class BaseRequest {
    baseUrl: string;
    headers:Record<string, string>;
    authStrategy: Strategy;
    
    constructor({ baseUrl , headers , authStrategy }: RequestsOptions) {
        this.baseUrl = baseUrl;
        this.headers = headers || {};
        this.authStrategy = authStrategy || new DefaultStrategy();
    }
    
    // private getDefaultsAuthOptions(authOptions?: AuthOptions): AuthOptions {
    //     return {
    //         authType: authOptions?.authType || "session",
    //         targetSource: authOptions?.targetSource || TargetSource.INSOURCE,
    //         token: authOptions?.token || "",
    //         authKey: authOptions?.authKey || "Authorization",
    //         authValue: authOptions?.authValue || "Bearer"
    //     };
    // }
}

/**
 * Handles request headers and authentication
 */
class HeadersRequestMaker extends BaseRequest {
    headers: Record<string, string>;
    
    constructor(options: RequestsOptions) {
        super(options);
        this.headers = this.getDefaultHeaders(options.headers);
        this.headers = this.authStrategy.applyHeaders(this.headers);
    }
    
    private getDefaultHeaders(headers?: Record<string, string>): Record<string, string> {
        return {
            ...headers,
            "Content-Type": "application/json",
            "Accept": "application/json"
        };
    }
}

/**
 * Core request handling class with HTTP method implementations
 */
class Requests extends HeadersRequestMaker {
    private getFullURL(route: string): string {
        const base = this.baseUrl.endsWith('/') 
            ? this.baseUrl.slice(0, -1) 
            : this.baseUrl;
        
        const path = route.startsWith('/') 
            ? route 
            : `/${route}`;
            
        return `${base}${path}`;
    }
    
    async send({ route, method, params, body }: RequestProps): Promise<Response> {
        const url = new URL(this.getFullURL(route));
        if (params) {
            Object.entries(params).forEach(([key, value]) => {
                url.searchParams.append(key, value.toString());
            });
        }
        return fetch(url.toString(), {
            method,
            credentials: this.authStrategy.authOptions.targetSource,
            headers: this.headers,
            body: body ? JSON.stringify(body) : undefined
        });
    }
}



/**
 * Enhanced requests class with interceptors and response parsing
 * Provides a clean API for making HTTP requests with automatic JSON parsing
 */
export class APIRequests extends Requests {
    interceptorManager: InterceptorManager;
    
    constructor(options: RequestsOptions & { authStrategy?: Strategy }) {
        super({
            ...options,
            authStrategy: options.authStrategy,
        });
        this.interceptorManager = new InterceptorManager();
    }
    
    async send(request: RequestProps): Promise<Response> {
        const interceptedRequest = await this.interceptorManager.executeInterceptors(
            request,
            InterceptorType.REQUEST
        );
        
        const response = await super.send(interceptedRequest);
        
        return this.interceptorManager.executeInterceptors(
            response,
            InterceptorType.RESPONSE
        );
    }
    
    async parseResponse<T>(response: Response): Promise<T> {
        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }
        
        const contentType = response.headers.get('Content-Type') || '';
        if (contentType.includes('application/json')) {
            return response.json();
        }
        return response.text() as unknown as T;
    }
    
    async get<T>(route: string, params?: Record<string, any>): Promise<T> {
        const response = await this.send({ route, method: Methods.GET, params });
        return this.parseResponse<T>(response);
    }
    
    async post<T>(route: string, body?: any, params?: Record<string, any>): Promise<T> {
        const response = await this.send({ route, method: Methods.POST, params, body });
        return this.parseResponse<T>(response);
    }
    
    async put<T>(route: string, body?: any, params?: Record<string, any>): Promise<T> {
        const response = await this.send({ route, method: Methods.PUT, params, body });
        return this.parseResponse<T>(response);
    }
    
    async patch<T>(route: string, body?: any, params?: Record<string, any>): Promise<T> {
        const response = await this.send({ route, method: Methods.PATCH, params, body });
        return this.parseResponse<T>(response);
    }
    
    async delete<T>(route: string, params?: Record<string, any>): Promise<T> {
        const response = await this.send({ route, method: Methods.DELETE, params });
        return this.parseResponse<T>(response);
    }
}
