const t = (arKey:string,enKey:string)=> ({ar:arKey,en:enKey})

export const BASE_URL = "/" //http://localhost:8000
export const BASE_URL_NESTJS = "/" //http://localhost:3000
export const BASE_URL_SOCKET = "/ws" //

export const CURRENT_VERSION = "0.2.1"

export const WEEK_DAYS = [
  t("الاحد","Sun"), 
  t("الاثنين","Mon"), 
  t("الثلاثاء","Tue"), 
  t("الاربعاء","Wed"), 
  t("الخميس","Thu"), 
  t("الجمعة","Fri"), 
  t("السبت","Sat")
]
// WhatsApp color constants
export const WHATSAPP_COLORS = {
  primary: "#128C7E",
  secondary: "#075E54",
  accent: "#25D366",
  background: "#ECE5DD",
  text: "#000000",
  lightText: "#FFFFFF"
};
export const LANGS = t("ar-EG","en-US")

export const numbersOptions = {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
  useGrouping: true,
}

export const TRANSLATIONS = {
  Direction:t('rtl','ltr'),
  Date:t("التاريخ","Date") ,
  Delete:t("مسح","Delete"),
  User:t("المستخدم" , "User"),
  WAInputMessage:{
    placeholder:t("اكتب رساله","Write a message")
  },
  SideBar:{
    Whatsapp:{
      title:t("واتساب","Whatsapp"),
      accounts:t("الحسابات","Accounts"),
      manager:t("مدير الواتساب","Whatsapp Manager"),
      distrbution:t("توزيع","Distribution"),
      

    },
    DashBoard:{
      title:t("الرئيسية","Dashboard"),
      market:t("داش ماركت","Dash Market")
    },
    FPDetails :{
      title:t("تفاصيل الحضور","FP Details"),
      Requests : t("الطلبات","Requests"),
      AttendanceDetails : t("تفاصيل الحضور","Attendance Details"),
      AttendanceDetailsLated : t("المتاخرين","Attendance Lated"),
      SalaryList:t("قائمة القبض","Salary List"),
    },
    Basic:{
      title:t("الأساسي","Basic"),
      actionPlan:t("الجزاءات","Action Plan"),
    },
    ReportSocial:{
      title:t("ريبورت سوشيال","Report Social"),
      report:t("اضافة ريبورت","Add Report"),
      view:t("مشاهدة الريبورتات","View Reports"),
      oldlead:t("مسح عميل قديم","Delete Old Lead")
    },
    Commission:{
      title:t("كوميشن","Commission"),
      Marketing:t("ماركت","Marketing")  ,
      Sales:t("سيلز","Sales"),
      Technical:t("تيكنكال","Technical"),
      General:t("جينرال","General"),
      All:t("الكل","All"),
      CoinChanger:t("سعر العملة","Coin Changer"),
      Leads:t("العملاء","Leads"),
    },
    Users:{
      title:t("المستخدمين","Users"),
      AddUser:t("اضافة مستخدم","Add User"),
      UsersList:t("قائمة المستخدمين","Users List"),
      DeviceAccess:t("الاجهزة المسموحة","Device Access"),
      Teams:t("الفرق","Teams"),
      TeamsPreview:t("تفاصيل الفرق","Team Details"),
    },
    General:{
      title:t("العام","General"),
      Notification:t("التنبيهات","Notification"),
      SalaryHistory:t("قبض الناس","SalaryHistory"),
    },
    Treasury:{
      title:t("الخزنة","Treasury"),
      Advance:t("السلف","Advance"),
      treasuryProjects :t("خزنة البروجيكتات","Treasury-Projects")
    },
  },
  Labels:[
    {label:"العربية",value:"ar"} ,
    {label:"English",value:"en"} ,
  ],
  Request:{
    Type:t("نوع الطلب","Request Type"),
    Types:[
      {
        value:"GLOBAL",
        translate:t("عام","Global")
      },
      {
        value:"VACATION",
        translate:t("اجازة","vacation")
      },
      {
        value:"DEPARTURE",
        translate:t("انصراف","departure")
      },
      {
        value:"LATE",
        translate:t("تأخير","Late")
      },
    ],
    Status:{
      PENDING : t("معلق","PENDING"),
      REJECTED : t("مرفوض","REJECTED"),
      ACCEPTED : t("مقبول","ACCEPTED"),
    },
    Details:t("التفاصيل","Details"),
    Date:t("التاريخ","Date"),
    Submit:t("ارسال","Send")
  },
  Dashboard:{
    middleLabel:t("تاريخ اليوم","Today's Date"),
    login:t("حضور" , "Login"),
    logout:t("انصراف" , "Logout"),
    Alerts:{
      Arrive:{
        onSuccess:t("تم الحضور بنجاح","Success Arrived") ,
        onFaild:t("فشل تسجيل الحصور","Faild to Arrived")
       
      },
      Leave:{
        onSuccess:t("تم الانصراف بنجاح","Success Leave") ,
        onFaild:t("فشل تسجيل الانصراف","Faild to Leave")
      }
    }
  },
  Login:{
    username:t("اسم المستخدم","Username"),
    password:t("كلمة المرور","Password"),
    SignIn:t("تسجيل الدخول","Sign In") ,
    ForgetPassword:t("لقد نسيت كلمة المرور","Forget Password"),
    Login:t("تسجيل الدخول","Login"),
    Alerts:{
      onSuccess:t("تم تسجيل الدخول بنجاح","Successfully Logged in"),
      onFaild:t("فشل تسجيل الدخول","Login failed")
    }
  },
  Profile: {
    Picture:t("صورة الملف الشخصى","Picture"),
    Phone:t("رقم الهاتف","Phone"),
    About:t("حول","About"),
    TelegramID:t("رقم التيلجرام ID","Telegram ID"),
    Department:t("القسم","Department"),
    Project:t("البروجيكت","Project"),
    Title:t("الترقية","Title"),
    Username:t("اسم المستخدم","Username"),
    Fullname:t("الاسم بالكامل","Full Name"),
    Alerts:{
      onSuccessUpdate:t("التحديث تم بنجاح","Success Update"),
      onFaildUpdate:t("فشل التحديث","Update Faild"),
      onSuccessCreated:t("نجح الانشاء","Created Successfully"),
      onFaildCreated:t("فشل الانشاء","Created Faild"),
      // onSuccessCreated:t("نجح الانشاء","Created Successfully"),
      // onFaildCreated:t("فشل الانشاء","Created Faild"),
    }
  },
  AttendanceLated:{
    title:t(" المتاخرين","Attendance Lated"),
    table:{
      headers: {
        ar:["صورة","المستخدم","التاريخ","يوم الاسبوع","حضور","انصراف","مدة الشيفت" , "التاخير" , "الانصراف مبكرا","الخصم"],
        en:["picture","User","date","DayOfWeek","arrived at","leaving at","deuration" , "late" , "departure","deduction"],
      },
    },
    bottomBar:{
      lateCount:t("عدد التاخيرات","Late Count"), 
      departureCount:t(" الانصراف مبكرا","Departure Count"), 
      AttendanceCount:t("عدد ايام الحضور","Attendance Count"), 
      DaysCount:t("عدد الايام","Days Count"), 
      deuctionCount:t("عدد ايام الخصم","Deduction Count (Days)"), 
      percentageCount:t("نسبة التاخير","Late Percentage")
    }
  },
  AttendanceDetails:{
    title:t("تفاصيل البصمة","Attendance Details"),
    table:{
      headers: {
        ar:["التاريخ","يوم الاسبوع","البروجيكت","حضور","انصراف","مدة الشيفت" , "التاخير" , "الانصراف مبكرا","الخصم"],
        en:["date","DayOfWeek","project","arrived at","leaving at","deuration" , "late" , "departure","deduction"],
      },
    },
    bottomBar:{
      lateCount:t("عدد التاخيرات","Late Count"), 
      departureCount:t(" الانصراف مبكرا","Departure Count"), 
      AttendanceCount:t("عدد ايام الحضور","Attendance Count"), 
      DaysCount:t("عدد الايام","Days Count"), 
      deuctionCount:t("عدد ايام الخصم","Deduction Count (Days)"), 
      percentageCount:t("نسبة التاخير","Late Percentage")
    }
  },
  Advance:{
    title:t("السلف","Advances"),
    table:{
      headers: {
        ar:["المستخدم","اسم المستخدم","المبلغ","تاريخ الانشاء"],
        en:["user","username","amount","created_at"],
      },
    },
    form:{
      taker:t("المُستَلِف","Taker"),
      amount:t("القيمة","Amount"),
      submit:t("تاكيد","Submit")
    } ,
    bottom:{
      request:t("طلب سلف","Request Advance"),
      totalCount:t("اجمالى عدد السلف","Total Advance count") ,
      total:t("اجمالى قيمة السلف","Total Advance") ,
    }
  },
  SpeedoMeter:{
    title:t("نسبة التاخيرات","Late Percentage")
  },
  Requests:{
    title:t("الطلبات","Requests"),
    table:{
      headers: {
        ar:["اسم المستخدم","نوع الطلب","الحالة","التفاصيل","التاريخ","ملاحظة","تاريخ الانشاء"],
        en:["username","type","status","details","date","note","created_at"],
      },
      headers2:{
        ar:["النوع","الحالة","التفاصيل","التاريخ","ملاحظة","اُنشئ فى"] ,
        en:["type","status","details","date","note","created_at"],
      }
    },
    bottom:{
      total:t("اجمالى عدد الطلبات","Total Requests"),
    },
  },
  Treasury:{
    total:t("قيمة الخزنة الحالية","Total Treasury"),
    outform:{
      title:t("المصروفات","Outcome"),
      details:t("التفاصيل","Details"),
      amount:t("القيمة","Amount"),
      clear:t("مسح","Clear"),
      submit:t("تاكيد","Submit") ,
    },
    inform:{
      title:t("الايرادات","Income"),
      details:t("التفاصيل","Details"),
      amount:t("القيمة","Amount"),
      submit:t("تاكيد","Submit") ,
      delete:t("مسح","Delete") ,
    },
    outtable:{
      title:t("جدول الصادرات","Outcome Table"),
      headers:{
        ar:["المستخدم","اسم المستخدم","القيمة","التفاصيل","مسح"],
        en:["creator","username","amount","details","delete"],
      },
    },
    intable:{
      title:t("جدول الواردات","Income Table"),
      headers:{
        ar:["اسم المستخدم","القيمة","التفاصيل","البروجيكت","تاريخ الانشاء","مسح"],
        en:["username","amount","details","project","created_at","delete"],
      },
    },
  },
  Notification:{
    form:{
      title:t("اضافة تنبيه","Add Notification"),
      message:t("الرسالة","Message"),
      sendto:t("ارسال الى","Send To") ,
      deadline:t("تاريخ الانتهاء","Deadline") ,
      send:t("ارسال","Send") ,
    },
    table:{
      title:t("جدول التنبيهات","Notification Table"),
      headers:{
        ar:["المستخدم","الرسالة","عدد المشاهدات","التاريخ الانتهاء"],
        en:["creator","message","seen count","deadline"],
      },
    }
  },
  Teams:{
    form:{
      title:t("اضافة فريق","Add Team"),
      name:t("اسم الفريق","Team Name"),
      leader:t("القائد","Leader"),
      members:t("الاعضاء","Members"),
      commission:t("شرائح التارجت","Commission Rules"),
      submit:t("تاكيد","Submit") ,
    },
    table:{
      title:t("جدول الفرق","Team Table"),
      headers:{
        ar:["القائد","الاسم","عدد الاعضاء"],
        en:["leader","name","members count"],
      },
    }
  },
  DeviceAccess:{
    form:{
      title:t("اضافة جهاز","Add Device"),
      user:t("المستخدم","User"),
      name:t("اسم الجهاز","Device Name"),
      id:t("كود الجهاز","Device ID"),
      add:t("اضافة","Add") ,
    },
    table:{
      title:t("جدول الأجهزة","Device Table"),
      headers:{
        ar:["اسم المستخدم","اسم الجهاز","كود الجهاز"],
        en:["username","name","device-id"],
      },
    }
  },
  UsersList: {
    title:t("قائمة المستخدمين","Users List"),
    headers:{
      ar:["صورة","اسم المستخدم","crm_username","كلمة السر","مُفَعّل","الصلاحيات","title","القسم","البروجيكت","رقم الهاتف","FP_ID","",""],
      en:["picture","username","crm_username","password","is active","role","title","department","project","Phone","FP_ID","",""],
    },
    filters:{
      department:t("القسم","Department"),
      project:t("البروجيكت","Project"),
      group:t("البروجيكتات","Projects Group"),
      role:t("الصلاحيات","Role"),

    },
  },
  AddUser:{
    form:{
      title:t("اضافة مستخدم","Add User"),
      username:t("اسم المستخدم","Username"),
      password:t("كلمة السر","Password"),
      first:t("الاسم الاول","First Name"),
      last:t("الاسم الاخير","Last Name"),
      usertitle:t("لقب","Title"),
      role:t("الصلاحيات","Role"),
      department:t("القسم","Department"),
      project:t("البروجيكت","Project"),
      crm_username:t("CRM Username","CRM Username"),
      fp_id:t("ID البصمة","Finger ID"),
      create:t("انشاء","Create"),
      cancel:t("الغاء","Cancel"),
    },
    commissionform:{
      title:t("تفاصيل المرتب","User Commission Details"),
      basic:t("الاساسى [EGP]","Basic in [ EGP ]"),
      setdeduction:t("تفعيل الخصومات العامة","Set Deduction Rules (Global)"),
      setcommission:t("تفعيل التارجت العام","Set Commission Rules (Global)"),
      deductionrules:t("الخصومات المخصصة","Deduction Rules (Custom)"),
      commissionrules:t("التارجت المخصص","Commission Rules (Custom)"),
      arrive:t("موعد الوصول","Arrive At"),
      leave:t("موعد المغادرة","Leave At"),
      save:t("حفظ","Save"),
      cancel:t("الغاء","Cancel"),
    }
  },
  Salary:{
    title:t("الرواتب","Salary"),
    table:{
      title:t("جدول الرواتب","Salary Table"),
      headers:{
        ar:["الصورة","بروجيكت التقفيل","اسم المستخدم","الصلاحيات","اللقب","القسم","البروجيكت","الاساسى","المرتب كامل"],
        en:["picture","Basic_project","username","role","title","department","project","basic","total-salary"],
      },
    },
    form:{
      title:t("الراتب","Salary"),
      target:t("التارجت","Target"),
      targetteam:t("تارجت الفريق","Target Team"),
      plus:t("بلس +5","Plus +5"),
      plus_10:t("بلس +10","Plus +10"),
      american:t("العملاء الامريكى","American Leads"),
      subscription:t("اشتراكات","Subscription"),
      americanSubscription:t("اشتراكات امريكى","American Subscription"),
      deduction:t("خصم","Deduction"),
      gift:t("مكافأة","Gift"),
      update:t("تحديث","Update"),
      give:t("اعطاء","Give"),
    }
  },
  Basic:{
    title:t("الاساسى","Basic"),
    annual:t("رصيد الاجازات","Annual"),
    table:{
      title:t("جدول الاساسى","Basic Table"),
      headers:{
        ar:["الصورة","بروجيكت الاساسى","اسم المستخدم","الصلاحيات","اللقب","الاساسى","القسم","البروجيكت","الاساسى الماخوذ",""],
        en:["picture","basic_project","username","role","title","basic","department","project","taked_basic",""],
      },
    },
    form:{
      deductiondays:t("خصم بالايام","Deduction Days"),
      deductionmoney:t("خصم بالقيمة","Deduction Money"),
      kpi:t("KPI","KPI"),
      gift:t("علاوة (مكافأة)","Additional Gift"),
      take_annual:t("الاجازات الاعتيادى","Annual"),
      give:t("اعطى","Give")
    }

  },
  TargetSliceCalc:{
    target : t("التارجت","Target"),
    title:t("تارجت فردى","Target Personal"),
    title2:t("تارجت الفريق","Target Team"),
    table:{
      headers:{
        ar:["اقل قيمة","اعلى قيمة","المقابل"],
        en:["min-value","max-value","cost"],
      }
    }
  },
  AddOldLead :{
    title:t("مسح ليدز دابل","Delete double leads")
  },
  ActionPlan :{
    title:t("الجزاءات","Action Plans"),
    table:{
      headers:{
        ar:["اسم المستخدم","الخصم","عنوان","وصف","التاريخ","الخاصم","تاريخ الانشاء","مسح"],
        en:["Username","Deduction_days","Title","Description","Date","Creator","Created_at","Delete"],
      },
      headersBasic:{
        ar:["الخصم","عنوان","وصف","التاريخ","الخاصم","تاريخ الانشاء"],
        en:["Deduction_days","Title","Description","Date","Creator","Created_at"],
      }
    },
    Form:{
      name:t("العنوان","Title"),
      deduction_days:t("ايام الخصم","Deduction Days")
    }
  }
}