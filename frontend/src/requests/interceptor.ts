import { InterceptorType } from "./types";
import { Interceptor } from "./types";
import { InterceptorReturnType } from "./types";


/**
 * Manages request and response interceptors
 * Handles registration, removal, and execution of interceptors
 */
export class InterceptorManager {
    interceptors: {
        interceptor: Interceptor<any>;
        rank: number;
        type: InterceptorType;
    }[] = [];
    
    addInterceptor(
        interceptor: Interceptor<any>,
        type: InterceptorType,
        rank: number = this.interceptors.length
    ) {
        this.interceptors.push({ interceptor, rank, type });
    }
    
    removeInterceptor(interceptor: Interceptor<any>) {
        this.interceptors = this.interceptors.filter(i => i.interceptor !== interceptor);
    }
    
    async executeInterceptors<T>(
        value: T,
        type: InterceptorType
    ): Promise<T> {
        let currentValue = value;
        const sortedInterceptors = [...this.interceptors]
            .filter(i => i.type === type)
            .sort((a, b) => a.rank - b.rank);
        
        for (const { interceptor } of sortedInterceptors) {
            if (!interceptor.interceptCall) continue;
            
            const result = await interceptor.interceptCall(currentValue);
            currentValue = interceptor.returnType === InterceptorReturnType.RETURN_ARG
                ? currentValue
                : result;
        }
        
        return currentValue;
    }
}
