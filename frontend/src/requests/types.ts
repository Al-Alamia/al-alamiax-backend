/**
 * HTTP methods supported by the request utility
 */
export enum Methods {
    GET = "GET",
    POST = "POST",
    PUT = "PUT",
    PATCH = "PATCH",
    DELETE = "DELETE"
}

/**
 * Type of authentication to be used
 */
export type AuthType = "jwt" | "session";

/**
 * Controls how cookies are handled in cross-origin requests
 */
export enum TargetSource {
    /** Include credentials in cross-origin requests */
    OUTSOURCE = "include",
    /** Only include credentials in same-origin requests */
    INSOURCE = "same-origin",
    /** Never include credentials */
    NEVER = "omit"
}

/**
 * Interface for request configuration
 */
export interface RequestProps {
    /** The API endpoint route */
    route: string;
    /** HTTP method to use */
    method: Methods;
    /** Optional query parameters */
    params?: Record<string, any>;
    /** Optional request body */
    body?: any;
}

/**
 * Authentication configuration options
 */
export interface AuthOptions {
    /** Type of authentication */
    authType: AuthType;
    /** How to handle credentials */
    targetSource?: TargetSource;
    /** Token getter function or token string */
    token: (() => string) | string;
    /** Header key for auth (e.g., 'Authorization') */
    authKey?: string;
    /** Auth scheme (e.g., 'Bearer') */
    authValue?: string;
}

/**
 * Base strategy class for authentication
 * Extend this class to implement custom authentication strategies
 */
export interface Strategy {
    authOptions: AuthOptions;
    applyHeaders(headers: Record<string, string>):Record<string, string>;  
}

/**
 * Configuration options for the Requests class
 */
export interface RequestsOptions {
    /** Base URL for all requests */
    baseUrl: string;
    /** Default headers to include in all requests */
    headers?: Record<string, string>;
    /** Authentication strategy to use */
    authStrategy?: Strategy;
}


/**
 * Determines how the interceptor affects the request/response chain
 */
export enum InterceptorReturnType {
    /** Continue with the original value */
    RETURN_ARG,
    /** Use the value returned by the interceptor */
    RETURN_INTERCEPTED
}

/**
 * Type of interceptor (request or response)
 */
export enum InterceptorType {
    /** Intercepts requests before they are sent */
    REQUEST,
    /** Intercepts responses before they are processed */
    RESPONSE
}

/**
 * Function type for interceptors
 * @template T Type of the value being intercepted (RequestProps or Response)
 */
export type InterceptorFn<T> = (arg: T) => T | Promise<T>;

/**
 * Interceptor for modifying requests or responses
 * @template T Type of the value being intercepted
 */
export class Interceptor<T> {
    constructor(
        public interceptCall?: InterceptorFn<T>,
        public returnType: InterceptorReturnType = InterceptorReturnType.RETURN_INTERCEPTED
    ) {}
}


/**
 * Standard paginated response format
 * @template T Type of items in the results array
 */
export interface PaginationResponse<T> {
    /** Array of paginated items */
    results: T[];
    /** URL to the previous page, or null if on first page */
    previous: string | null;
    /** URL to the next page, or null if on last page */
    next: string | null;
    /** Number of items in the current page */
    count: number;
    /** Total number of items across all pages (optional) */

    total_count?: number;
}