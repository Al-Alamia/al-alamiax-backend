import  {type FC , useContext, useEffect, useState} from 'react';
import Container from '../../layouts/Container/Container';
import useRequest from '../../hooks/calls';
import { convertObjectToArrays, getFullURL } from '../../utils/converter';
import { Department, Project, User } from '../../types/auth';
import { FaHandHoldingUsd, FaUserEdit } from "react-icons/fa";
import { Link } from 'react-router-dom';
import LoadingComponent from '../../components/LoadingComponent/LoadingComponent';
import Table from '../../components/Table/Table';
// import CustomDatePicker from '../../components/CustomDatePicker/CustomDatePicker';
import { useAuth } from '../../hooks/auth';
import { LanguageContext } from '../../contexts/LanguageContext';
import { TRANSLATIONS } from '../../utils/constants';
import DatePicker from 'react-datepicker';
import TableFilters from '../../components/UsersTable/TableFilters/TableFilters';
import { checkPermission } from '../../utils/permissions/permissions';
import { loadDateFilter , saveDateFilter , loadSearchFilter , saveSearchFilter } from '../../utils/storage';

interface SalaryAllProps {
    department__name?: string;
}


const SalaryAll: FC<SalaryAllProps> = ({department__name}) => {
    const [date, setDate] = useState<Date>(new Date());
    const {auth} = useAuth();
    const {lang} = useContext(LanguageContext);
    // const [projects,setProjects] = useState<Set<Project>>()
    const [projects,setProjects] = useState<Set<string | undefined>>()
    const additionalFilter = department__name ? {department__name} : {}
    const [filters, setFilters] = useState<object>()
    const { data, loading } = useRequest<User>(
        {
            url: "api/commission/users-commission",
            method: "GET",
            params: { 
                date :`${date.getFullYear()}-${date.getMonth()+1}` ,
                ...filters ,
                ...additionalFilter ,
            },
        },
        [date , department__name , filters],
        undefined,500
    );
    useEffect(()=>{
        // setProjects(new Set(
        //     data?.results.map((val , indx , arr)=> val.project ).filter((obj,ind,arr)=>{
        //         return ind === arr.findIndex((other)=>  other.uuid === obj.uuid && other.name === obj.name )})
        // ))       
        setProjects(new Set(
            data?.results.filter((obj,ind,arr)=>obj.basic_project_name ? true :false).map((val , indx , arr)=> val.basic_project_name ).filter((obj,ind,arr)=>{
                return obj &&  ind === arr.findIndex((other)=>  other === obj )})
        ))
    },[data])
    useEffect(()=>{
        const location = window.location.pathname.toString()
        setDate(loadDateFilter(location))
        setFilters(loadSearchFilter(location))
    },[])
    if (checkPermission(auth,"view_commission")){
        const canBasic = checkPermission(auth,"add_basic")
        const canSalary = checkPermission(auth,"add_commission")

        return (
        <div className='flex justify-center'>
            <Container className='w-fit md:w-screen h-fit min-h-[500px] relative gap-3 justify-center items-center '>
            <h1 className='text-2xl text-btns-colors-primary text-center w-full'>{TRANSLATIONS.Salary.title[lang]} - {department__name ? department__name : "All"} - {date.getFullYear()}-{date.getMonth()+1}</h1>
            <div className="col-span-full mt-4 gap-8 flex justify-center">
                <TableFilters className='md:px-16' setFilters={setFilters} searchValue={filters ?( filters as {username__contains:string}).username__contains : ""} filtersCallBack={(filters:object)=>saveSearchFilter(window.location.pathname.toString(),filters)} others={false}/>
                <h1 className="text-2xl text-center ">
                    {TRANSLATIONS.Date[lang]} 
                </h1>
                <DatePicker 
                    showIcon
                    dateFormat="MM-yyyy"
                    name='date' 
                    renderMonthContent={ (month, shortMonth, longMonth, day) => {
                        const fullYear = new Date(day).getFullYear();
                        const tooltipText = `Tooltip for month: ${longMonth} ${fullYear}`;
                        return <span title={tooltipText}>{shortMonth}</span>;
                    }} 
                    toggleCalendarOnIconClick
                    showMonthYearPicker 
                    className=' h-11 text-center' 
                    calendarIconClassName='w-4 h-4 fixed p-1'
                    selected={date} 
                    onChange={(date)=>{
                        if(date && setDate) {
                            saveDateFilter(window.location.pathname.toString(),date)
                            setDate(date)
                        };
                    }
                }/>
            </div>
            {
                loading? <LoadingComponent/> : <></>
            }
            {
                data ? (
                    <>
                    <Table
                        className='mb-2'
                        headers={TRANSLATIONS.Salary.table.headers[lang]}
                        data={convertObjectToArrays(data?.results,[
                            {
                                key:"profile",
                                method : (_)=>{
                                    const item = _ as any; 
                                    return (
                                            <td key={Math.random()} className='flex justify-center items-center px-3 py-1'>
                                                {
                                                    item.picture ? <img src={getFullURL(item.picture)} alt="" className='rounded-full w-[40px] h-[40px]'/> : "-"
                                                }
                                            </td>
                                    )}
        
                            },
                            {
                                key:["basic_project_name","project"],
                                method: (_) => {
                                    const {basic_project_name="-" , project={name:"-"} } = _ as any;
                                    return basic_project_name ? basic_project_name : (
                                        <td
                                            key={Math.random()}
                                            className="text-center w-[40px] h-[40px] px-3 py-1"
                                        >
                                            {project.name}
                                        </td>
                                    );
                                }
                            },
                            {
                                key:"username",
                                method:null
                            },
                            {
                                key:"role",
                                method:null
                            },{
                                key:"title",
                                method:null
                            },{
                                key:"department",
                                method:(item)=>{
                                    const depart = item as any; 
                                    return depart.name
                                }
                            },{
                                key:"project",
                                method:(item)=>{
                                    const project = item as any; 
                                    return project.name
                                }
                            },{
                                key:["has_basic","uuid"],
                                method : (args)=>{
                                    const {has_basic,uuid} = args as any;
                                    return (
                                        <td key={Math.random()} className='px-3 py-1'>
                                            {
                                                canBasic ? 
                                                <Link className='rounded-md w-2/3 h-8' to={`/user-basic/${uuid}/${date.getMonth()+1}-${date.getFullYear()}`} >
                                                    <FaHandHoldingUsd className={`${has_basic ? "fill-btns-colors-primary" : "fill-btns-colors-secondry"} w-full h-6 text-center`}/>
                                                    {has_basic}
                                                </Link>
                                                : has_basic
                                            }
                                        </td>
                                    )
                                }
                            },{
                                key:["has_commission","uuid"],
                                method : (args)=>{
                                    const {has_commission,uuid} = args as any;
                                    return (
                                        <td key={Math.random()} className='px-3 py-1'>
                                            {
                                                canSalary ?
                                                <Link className='rounded-md w-2/3 h-8' to={`/salary/${uuid}/${date.getMonth()+1}-${date.getFullYear()}`} >
                                                    <FaHandHoldingUsd className={`${has_commission ? "fill-btns-colors-primary" : "fill-btns-colors-secondry"} w-full h-6 text-center`}/>
                                                    {has_commission}
                                                </Link>
                                                : has_commission
                                            }
                                        </td>
                                    )
                                }
                            },
                        ])}
                    
                    />
                    <div className='flex flex-row rounded-md h-10 min-w-[950px] md:min-w-[1000px] items-center justify-evenly bg-light-colors-dashboard-third-bg dark:bg-dark-colors-login-third-bg md:w-full'>
                        {
                            projects ? 
                            
                            Array.from(projects).map((val)=>{
                                return (<>
                                <div className='w-full text-center' key={Math.random()}>
                                    {val} : {data?.results.filter((u,ind,arr)=>u?.basic_project_name===val).reduce((total,obj)=>total+ ( obj?.has_commission ? obj?.has_commission : 0),0)} EGP
                                </div>
                                </>)
                                }
                            ) 
                            :

                            <></>
                        }
                    </div>
                    <div className='flex flex-row rounded-md h-10 min-w-[950px] md:min-w-[1000px] items-center justify-evenly  md:w-full'>
                        {
                            data?.results && projects ? (
                                <div className='w-full text-center' key={Math.random()}>
                                    Total Salaries : {(data?.results as any).reduce((total:number,obj:any)=>total+ ( obj?.has_commission ? obj?.has_commission : 0),0)} EGP
                                </div>
                            ) : <></>
                        }
                    </div>
                </>
                ):<></>
            }


            

            </Container>
        </div>);}
    return null
}

export default SalaryAll;
