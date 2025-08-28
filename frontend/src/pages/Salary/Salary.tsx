import { useContext, useEffect, useState, type FC } from 'react';
import TargetSliceCalc from '../../components/TargetSliceCalc/TargetSliceCalc';
import TotalLeadsCard, { TotalLeads } from '../../components/TotalLeadsCard/TotalLeadsCard';
import SalaryForm from '../../components/SalaryForm/SalaryForm';
import { useParams } from 'react-router-dom';
import { parseDateFromParams } from '../../utils/converter';
import { sendRequest } from '../../calls/base';
import { BasicDetails, CommissionDetails, Subscription, User } from '../../types/auth';
import BasicForm from '../../components/BasicForm/BasicForm';
import LoadingPage from '../LoadingPage/LoadingPage';
import { LanguageContext } from '../../contexts/LanguageContext';
import { TRANSLATIONS } from '../../utils/constants';
import { checkPermission } from '../../utils/permissions/permissions';
import { useAuth } from '../../hooks/auth';
import { Project } from '../../types/auth';

interface SalaryProps {}

export interface SalaryType {
    uuid:string;
    basic?:BasicDetails|string;
    user?:User|string;
    target: number;
    target_count: number;
    target_Team: number;
    target_Team_count: number;
    plus: number;
    plus_count: number;
    plus_10: number;
    plus_10_count: number;
    american: number;
    american_count: number;
    subscriptions:number;
    subscriptions_count:number;
    american_subscriptions:number;
    american_subscriptions_count:number;
    deduction: number;
    gift: number;
    salary: number;
    project:Project|null;
}

const Salary: FC<SalaryProps> = () => {
    const {lang} = useContext(LanguageContext)
    const {auth} = useAuth()
    const [loading , setLoading] = useState(false);
    const {user_uuid="",date=""} = useParams()
    const date_parsed = parseDateFromParams(date)
    const [userCommissionDetails,setUserCommissionDetails] = useState<CommissionDetails|null>(null)
    const [basicDetails , setBasicDetails] = useState<BasicDetails|null>(null)
    const [analytics, setAnalytics] = useState<TotalLeads|null>(null)
    const [subscriptions , setSubscriptions] = useState<Subscription[] | null>()
    const [americanSubscriptions , setAmericanSubscriptions] = useState<Subscription[] | null>()
    const [coinChanger, setCoinChanger] = useState<{egp_to_sar:number , date:string}|undefined>(undefined)
    const [oldSalary , setOldSalary] = useState<SalaryType|null>(null)
    useEffect(()=>{
        setLoading(true)

        const date_parsed = parseDateFromParams(date)


        const commissionPromise = sendRequest({url:"api/commission/user-commission-details",method:"GET",params:{user__uuid:user_uuid}})
        const detailsPromise = sendRequest({url:"api/commission/basic-details",method:"GET",params:{
            user__uuid:user_uuid,
            date__year:date_parsed.getFullYear() ,
            date__month:date_parsed.getMonth() + 1 
        }})
        const userLeadsPromise =   sendRequest({url:`api/users/user-leads`, method:"POST",params:{user_uuid:user_uuid , year : date_parsed.getFullYear() , month :date_parsed.getMonth()+1 }})
        const subscriptionPromise = sendRequest({url:`api/commission/subscription`, method:"GET" })  
        const americanSubscriptionPromise = sendRequest({url:`api/commission/american-subscription`, method:"GET" })  
        const oldSalaryPromise = sendRequest({url:`api/commission/salary`, method:"GET",params:{
            user__uuid:user_uuid,
            date__year:date_parsed.getFullYear(),
            date__month:date_parsed.getMonth() + 1,
        }})
        Promise.all([commissionPromise, detailsPromise , userLeadsPromise , subscriptionPromise , oldSalaryPromise ,americanSubscriptionPromise])
        .then(values=>{
            setUserCommissionDetails(values[0]?.results[0])
            setBasicDetails(values[1]?.results[0])
            setAnalytics(values[2])
            setSubscriptions(values[3].results)
            setAmericanSubscriptions(values[5].results)
            if (values[0]?.results[0].user.department.name.toLowerCase() === "sales"){
                sendRequest({url:`api/commission/coin-changer`, method:"GET" , 
                        params:{
                            date__year:date_parsed.getFullYear() ,
                            date__month:date_parsed.getMonth() + 1 
                        }
                    })  
                .then((data)=>{setCoinChanger(data?.results[0])})                    
            }
            if(values[4]?.results?.length > 0){
                setOldSalary(values[4]?.results[0])
            }
        })
        .finally(()=> setLoading(false) );
    },[])

    const canSalary = checkPermission(auth,"add_commission")
    return (
    <div className='salary flex flex-col h-fit justify-center'>
    <label className='text-4xl text-center'>Salary | {userCommissionDetails?.user.first_name} {userCommissionDetails?.user.last_name} ({userCommissionDetails?.user.username}) | {date} </label>
    <div className='grid grid-cols-1 md:grid-cols-12'>

        {
            loading ? <LoadingPage/> : null
        }

        {
            canSalary && analytics && basicDetails && userCommissionDetails? 
            <SalaryForm 
                oldSalary={oldSalary ? oldSalary : undefined} 
                analytics={analytics} 
                user_uuid={userCommissionDetails?.user.uuid} 
                basic={basicDetails} 
                department={userCommissionDetails?.user.department.name.toLowerCase()}  
                subscriptions={subscriptions} 
                american={americanSubscriptions} 
                className='col-span-4 place-self-center' 
                date={date_parsed}
                coinChange={coinChanger}
            />
            :null
        }
        <div className={`col-span-4 place-self-center`}>
            {
                userCommissionDetails?.user.department.name.toLowerCase() === "marketing" && analytics ?
                    <TotalLeadsCard analytics={analytics} className='col-span-4 place-self-center w-full' uuid={user_uuid} year={date_parsed.getFullYear()} month={date_parsed.getMonth()+1}/>
                :
                
                userCommissionDetails?.user.department.name.toLowerCase() === "sales" ?
                null
                : null
            }
            {
                userCommissionDetails && basicDetails? (
                    <BasicForm disabled={true} basicDetails={basicDetails ? basicDetails : undefined} date={date} userCommissionDetails={userCommissionDetails} className='place-self-center w-full'/>
                ) : null
            }
        </div>
        <div className='col-span-4 place-self-center'>
            <TargetSliceCalc className='col-span-4 place-self-center' uuid={user_uuid} name={TRANSLATIONS.TargetSliceCalc.title[lang]} target={0} coinChange={coinChanger}/>
            <TargetSliceCalc className='col-span-4 place-self-center' uuid={user_uuid} name={TRANSLATIONS.TargetSliceCalc.title2[lang]} coinChange={coinChanger} params={{table_type:"team"}}/>
        </div>

    </div>
    </div>
);
}

export default Salary;
