using System;
using System.Linq;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

namespace PT105_hex_to_blt_swdpat
{
    class PT105_Blt_Program
    {
        //public static string StilPath = @"D:\\CP_Pattern\\Start\\";
        //public static string StilPath_new = @"D:\\CP_Pattern\\end\\";

        public static string StilPath = @"D:\\01_Work\\CP_Map_Change\\Hex\\";
        public static string StilPath_new = @"D:\\01_Work\\CP_Map_Change\\Pat\\";

        //public static string StilPath = AppDomain.CurrentDomain.BaseDirectory;
        //public static string StilPath_new = AppDomain.CurrentDomain.BaseDirectory;

        public static int cyc_count = 0;
        public static bool addr_first = true;
        public static int addr_end_num = 0;

        public static int WriteSize = 0x30000042;
        public static int ReadSize = 0x20000042;
        public static int PageSize = 0x200;

        public static int Erase_delay = 70000;//T=1uS,Erase=5mS, 5000
        public static int Pgm_delay = 20000;//T=1uS,Pgm=1.5mS, 1500
        public static int ExLineAddr = 0;//扩展线性地址
        public static int Flash_Addr = 0x04100000;


        static void Main(string[] args)
        {

            DirectoryInfo root = new DirectoryInfo(StilPath);
            FileInfo[] thefileInfo = root.GetFiles("*.hex");

            foreach (FileInfo NextFile in thefileInfo)
            {
                cyc_count = 0;
                string strFileName = NextFile.Name.Substring(0, NextFile.Name.IndexOf(".hex"));//获取新生成的pat文件名
                Console.WriteLine(strFileName);
                if (Read(NextFile.FullName, strFileName))
                    Console.WriteLine("解析成功");
                else
                    Console.WriteLine("解析失败");

                addr_first = true;
                addr_end_num = 0;
            }
            Console.ReadLine();
        }

        static public bool Read(string pathSrc, string pathDet)
        {
            bool bSuccess = true;
            ExLineAddr = 0;

            StreamReader sr = new StreamReader(pathSrc, Encoding.Default);
            StreamWriter sw = new StreamWriter(StilPath_new + pathDet + "_swd" + ".pat");

            //SCLK,SDA
            string InitialStr = " *11*;";//初始字符串
            string line = "";

            Pat_header(sw, pathDet);
            SWD_Check_Start(sw);
            SWD_WriteKEY(sw, InitialStr);
            Load_Flash_register(sw, InitialStr);
            Page_Erase_Test(sw, InitialStr);


            sw.WriteLine("//bank0_pgm_start");

            SWD_Write_Addr(sw, InitialStr, 0x41000014);//FLASH_CR
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x01000001);//flash_pgm
			
			//SYS_PGM
            SWD_Write_Addr(sw, InitialStr, 0x410002EC);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x00000001);

            //write
            while ((line = sr.ReadLine()) != null)
            {
                if (line.Contains(":02000004"))
                {
                    ExLineAddr = AddrStr_to_int(line.Substring(9, 4)) * 0x10000;
                    //Console.WriteLine("0x{0:X}",ExLineAddr);

                    if (ExLineAddr == 0x70000)
                    {
                        sw.WriteLine("//bank1_pgm_start");
                    }
                }
                else if (line.Contains(":00000001FF"))
                { break; }

                Write_pat(sw, line, InitialStr);
            }

            
            sr.Close();

            sr = new StreamReader(pathSrc, Encoding.Default);
            //read
            while ((line = sr.ReadLine()) != null)
            {
                Read_pat(sw, line, InitialStr);
            }
            

            Pat_end(sw);
            sr.Close();
            sw.Close();
            return bSuccess;
        }

        static void Pat_header(StreamWriter sw, string TxtName)
        {
            string PatName = "SPM_PATTERN() {";
            PatName = PatName.Insert(PatName.IndexOf("(") + 1, TxtName + "_swd");

            sw.WriteLine("SET_DEC_FILE  \"pin.dec\"");
            sw.WriteLine("");
            sw.WriteLine("HEADER");
            sw.WriteLine("PA12,PA11,NRST;");//SCLK,SDA,PF5
            sw.WriteLine(PatName);
            sw.WriteLine("");

            sw.WriteLine(" *011*TS2;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
        }

        static void Pat_end(StreamWriter sw)
        {
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 53;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *011*STOP;");
            sw.WriteLine("}");
        }


        /// <summary>
        /// ARM M52内核，JTAG TO Dormant TO SWD
        /// Check ID CODE 0x4C01 3477
        /// </summary>
        /// <param name="sw"></param>
        static void SWD_Check_Start(StreamWriter sw)
        {
            sw.WriteLine(" *111*RPT 34 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 3 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 3 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 3 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 3 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 3 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 3 ;");
            sw.WriteLine(" *101*RPT 2 ;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 17 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 2 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 2 ;");
            sw.WriteLine(" *111*RPT 3 ;");
            sw.WriteLine(" *101*RPT 2 ;");
            sw.WriteLine(" *111*RPT 5 ;");
            sw.WriteLine(" *101*RPT 2 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 5 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 3 ;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 2 ;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 2 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 4 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*RPT 4 ;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*RPT 2 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 7 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 3 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 4 ;");
            sw.WriteLine(" *101*RPT 3 ;");
            sw.WriteLine(" *111*RPT 3 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 3 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 3 ;");
            sw.WriteLine(" *101*RPT 6 ;");
            sw.WriteLine(" *111*RPT 4 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*RPT 2 ;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*RPT 8 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*RPT 12 ;");
            sw.WriteLine(" *111*RPT 50 ;");
            sw.WriteLine(" *101*RPT 21 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 2 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 2 ;");
            sw.WriteLine(" *1H1*RPT 3 ;");//IDCode M52 0x4C01 3477
            sw.WriteLine(" *1L1*;");
            sw.WriteLine(" *1H1*RPT 3 ;");
            sw.WriteLine(" *1L1*RPT 3 ;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*;");
            sw.WriteLine(" *1H1*RPT 2 ;");
            sw.WriteLine(" *1L1*RPT 2 ;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 9 ;");
            sw.WriteLine(" *1H1*RPT 2 ;");
            sw.WriteLine(" *1L1*RPT 2 ;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1X1*;");



            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 2 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 2 ;");
            sw.WriteLine(" *1X1*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 3 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 21 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*RPT 2 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 2 ;");
            sw.WriteLine(" *1X1*;");
            sw.WriteLine(" *101*RPT 28 ;");//0x5000 0000
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 3 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 3 ;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 2 ;");
            sw.WriteLine(" *1X1*;");
            sw.WriteLine(" *101*RPT 37 ;");//0x0000 0000


            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*RPT 3 ;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 30 ;");
            sw.WriteLine(" *1H1*RPT 4 ;");
            sw.WriteLine(" *1L1*;");
            sw.WriteLine(" *1X1*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 3 ;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 2 ;");
            sw.WriteLine(" *1X1*;");
            sw.WriteLine(" *101*RPT 8 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*RPT 20 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 14 ;");

            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*RPT 3 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 2 ;");
            sw.WriteLine(" *1X1*;");
            sw.WriteLine(" *101*;");     //0x0000 0042
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 4 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 50 ;");

            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*RPT 3 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 2 ;");
            sw.WriteLine(" *1X1*;");
            sw.WriteLine(" *101*;");      //0x3000 0042
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 4 ;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 21 ;");
            sw.WriteLine(" *111*RPT 2 ;");
            sw.WriteLine(" *101*RPT 3 ;");

        }

        static void SWD_WriteKEY(StreamWriter sw, String InitialStr)
        {
            /*
            SWD_Write_Addr(sw, InitialStr, 0xE000EDF0);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0xA05F0003);//Stop CPU,开启Debug Mode
            */

            //FLASH_KEYR1
            SWD_Write_Addr(sw, InitialStr, 0x41000008);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x45670123);
            //FLASH_KEYR2
            SWD_Write_Addr(sw, InitialStr, 0x41000008);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0xCDEF89AB);

            //FLASH_OPTKEYR1
            SWD_Write_Addr(sw, InitialStr, 0x4100000C);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x08192A3B);
            //FLASH_OPTKEYR2
            SWD_Write_Addr(sw, InitialStr, 0x4100000C);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x4C5D6E7F);

            /*
            //FLASH_TESTKEYR1
            SWD_Write_Addr(sw, InitialStr, 0x410002D8);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x5D7F4051);
            //FLASH_TESTKEYR2
            SWD_Write_Addr(sw, InitialStr, 0x410002D8);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x46CE2763);
            */

            //FLASH_SMKEYR
            SWD_Write_Addr(sw, InitialStr, 0x410002DC);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x62734051);
            //FLASH_SMKEYR
            SWD_Write_Addr(sw, InitialStr, 0x410002DC);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x46CE57DF);


            //SYS_ERASE
            SWD_Write_Addr(sw, InitialStr, 0x410002EC);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x00000002);

        }

        //置位FLASH_CR寄存器的MER位和EOPIE位
        static void SWD_Write_MER_EOPIE(StreamWriter sw, String InitialStr)
        {
            SWD_Write_Addr(sw, InitialStr, 0x41000014);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x01000002);//page_erase
        }

        static void SWD_Write_main_anyvalue(StreamWriter sw, String InitialStr, int addr)
        {
            SWD_Write_Addr(sw, InitialStr, addr);
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x12345678);
        }

        static void Load_Flash_register(StreamWriter sw, String InitialStr)
        {
            //加载Param信息
            SWD_Write_Addr(sw, InitialStr, 0x41000100);//FLASH_TS0
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x0000001E);

            SWD_Write_Addr(sw, InitialStr, 0x41000104);//FLASH_TS1
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x00000048);

            SWD_Write_Addr(sw, InitialStr, 0x41000108);//FLASH_TS2P
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x0000001E);

            SWD_Write_Addr(sw, InitialStr, 0x4100010C);//FLASH_TPS3
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x00000120);

            SWD_Write_Addr(sw, InitialStr, 0x41000110);//FLASH_TS3
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x0000001E);

            SWD_Write_Addr(sw, InitialStr, 0x41000114);//FLASH_ERSTPE
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x00006D60);

            SWD_Write_Addr(sw, InitialStr, 0x41000118);//FLASH_PRGTPE
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x00001770);

            SWD_Write_Addr(sw, InitialStr, 0x4100011C);//FLASH_PRETPE
            //SWD_Write_Fix(sw, InitialStr, WriteSize);
            SWD_Write_Data(sw, InitialStr, 0x00000320);



        }

        static void Page_Erase_Test(StreamWriter sw, String InitialStr)
        {
            for (int index = 0; index < 10; index++)
            {
                SWD_Write_MER_EOPIE(sw, InitialStr);
                SWD_Write_main_anyvalue(sw, InitialStr, Flash_Addr + index * 512);
                Erase_PEdelay_test(sw, InitialStr);
            }
        }

        static void SWD_Write_Addr(StreamWriter sw, String InitialStr, long addr)
        {
            sw.WriteLine(" *111*RPT 2;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*RPT 3;");
            sw.WriteLine(" *111*RPT 2;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 2;");
            sw.WriteLine(" *1X1*;");
            //sw.WriteLine(" *101*;");

            string AddrStr = Convert.ToString(addr, 2).PadLeft(32, '0');//将int类型的值转换为32bit长度的字符串
            AddrStr = new string(AddrStr.ToCharArray().Reverse().ToArray());//倒转字符串
            string AddrStr_rep = AddrStr.Replace("1", "");
            int Parity_bit = 0;
            if ((AddrStr.Length - AddrStr_rep.Length) % 2 != 0) Parity_bit = 1;//判断奇偶校验码的值

            for (int i = 0; i < AddrStr.Length; i++)
            {
                if (i == 0)
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, AddrStr.Substring(i, 1)) + "//" + string.Format("{0:x8}", addr));
                else
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, AddrStr.Substring(i, 1)));
            }
            sw.WriteLine(" *1" + Parity_bit.ToString() + "1*;");
            sw.WriteLine(" *101*RPT 19;");
        }


        static void SWD_Write_Fix(StreamWriter sw, String InitialStr, long addr)
        {
            sw.WriteLine(" *111*RPT 2;");
            sw.WriteLine(" *101*RPT 3;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 2;");
            sw.WriteLine(" *1X1*;");
            //sw.WriteLine(" *101*;");

            string AddrStr = Convert.ToString(addr, 2).PadLeft(32, '0');//将int类型的值转换为32bit长度的字符串
            AddrStr = new string(AddrStr.ToCharArray().Reverse().ToArray());//倒转字符串
            string AddrStr_rep = AddrStr.Replace("1", "");
            int Parity_bit = 0;
            if ((AddrStr.Length - AddrStr_rep.Length) % 2 != 0) Parity_bit = 1;//判断奇偶校验码的值

            for (int i = 0; i < AddrStr.Length; i++)
            {
                if (i == 0)
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, AddrStr.Substring(i, 1)) + "//" + string.Format("{0:x8}", addr));
                else
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, AddrStr.Substring(i, 1)));
            }
            sw.WriteLine(" *1" + Parity_bit.ToString() + "1*;");
            sw.WriteLine(" *101*RPT 3;");
        }



        static void SWD_Write_Data(StreamWriter sw, String InitialStr, long data)
        {
            sw.WriteLine(" *111*RPT 2;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 3;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 2;");
            sw.WriteLine(" *1X1*;");
            //sw.WriteLine(" *101*;");

            string DataStr = Convert.ToString(data, 2).PadLeft(32, '0');//将int类型的值转换为32bit长度的字符串
            DataStr = new string(DataStr.ToCharArray().Reverse().ToArray());//倒转字符串

            string DataStr_rep = DataStr.Replace("1", "");
            int Parity_bit = 0;
            if ((DataStr.Length - DataStr_rep.Length) % 2 != 0) Parity_bit = 1;//判断奇偶校验码的值

            for (int i = 0; i < DataStr.Length; i++)
            {
                if (i == 0)
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataStr.Substring(i, 1)) + "//" + string.Format("{0:x8}", data));
                else
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataStr.Substring(i, 1)));
            }
            sw.WriteLine(" *1" + Parity_bit.ToString() + "1*;");
            sw.WriteLine(" *101*RPT 53;");
        }


        static void SWD_Read_Fix(StreamWriter sw, String InitialStr, long addr)
        {
            sw.WriteLine(" *111*RPT 2;");
            sw.WriteLine(" *101*RPT 3;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 2;");
            sw.WriteLine(" *1X1*;");
            //sw.WriteLine(" *101*;");

            string AddrStr = Convert.ToString(addr, 2).PadLeft(32, '0');//将int类型的值转换为32bit长度的字符串
            AddrStr = new string(AddrStr.ToCharArray().Reverse().ToArray());//倒转字符串
            string AddrStr_rep = AddrStr.Replace("1", "");
            int Parity_bit = 0;
            if ((AddrStr.Length - AddrStr_rep.Length) % 2 != 0) Parity_bit = 1;//判断奇偶校验码的值

            for (int i = 0; i < AddrStr.Length; i++)
            {
                if (i == 0)
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, AddrStr.Substring(i, 1)) + "//" + string.Format("{0:x8}", addr));
                else
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, AddrStr.Substring(i, 1)));
            }
            sw.WriteLine(" *1" + Parity_bit.ToString() + "1*;");
            sw.WriteLine(" *101*RPT 30;");//3->30 highspeed

            sw.WriteLine(" *111*RPT 5;");
            sw.WriteLine(" *101*RPT 2;");
            sw.WriteLine(" *111*RPT 2;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1X1*RPT 35;");
            sw.WriteLine(" *1X1*;");
            sw.WriteLine(" *101*RPT 2;");
        }

        static void SWD_Read_Data(StreamWriter sw, String InitialStr, long data)
        {
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 4;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*RPT 2;");
            sw.WriteLine(" *1H1*;");
            sw.WriteLine(" *1L1*RPT 2;");

            string DataStr = Convert.ToString(data, 2).PadLeft(32, '0');//将int类型的值转换为32bit长度的字符串
            DataStr = new string(DataStr.ToCharArray().Reverse().ToArray());//倒转字符串
            DataStr = DataStr.Replace('1', 'H');
            DataStr = DataStr.Replace('0', 'L');

            string DataStr_rep = DataStr.Replace("H", "");
            int Parity_bit = 0;
            if ((DataStr.Length - DataStr_rep.Length) % 2 != 0) Parity_bit = 1;//判断奇偶校验码的值

            for (int i = 0; i < DataStr.Length; i++)
            {
                if (i == 0)
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataStr.Substring(i, 1)) + "//" + string.Format("{0:x8}", data));
                else
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataStr.Substring(i, 1)));
            }
            sw.WriteLine(" *1" + Parity_bit.ToString().Replace('1', 'H').Replace('0', 'L') + "1*;");
            sw.WriteLine(" *1X1*;");
            sw.WriteLine(" *101*RPT 52;");
        }


        static void Erase_Delay_pt061(StreamWriter sw)
        {

            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");//sw.WriteLine(" *111*TS5;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT " + (Erase_delay * 1.5).ToString() + ";");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 500;");//sw.WriteLine(" *111*TS1;");
            sw.WriteLine(" *101*;");
        }

        static void Prog_Delay_pt061(StreamWriter sw)
        {
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");//sw.WriteLine(" *111*TS6;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT " + (Pgm_delay * 1.5).ToString() + ";");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 100;");//sw.WriteLine(" *111*TS1;");
            sw.WriteLine(" *101*;");
        }

        static void Prog_PEdelay_test(StreamWriter sw, String InitialStr)
        {

            Prog_Delay_pt061(sw);

            SWD_Write_Addr(sw, InitialStr, 0x41000010);//addr,置位FLASH_SR寄存器EOP位和BSY位
            //SWD_Write_Fix(sw, InitialStr, WriteSize);//addr
            SWD_Write_Data(sw, InitialStr, 0x00000001);

        }

        static void Erase_PEdelay_test(StreamWriter sw, String InitialStr)
        {

            Erase_Delay_pt061(sw);

            SWD_Write_Addr(sw, InitialStr, 0x41000010);//addr,置位FLASH_SR寄存器EOP位和BSY位
            //SWD_Write_Fix(sw, InitialStr, WriteSize);//addr
            SWD_Write_Data(sw, InitialStr, 0x00000001);

        }


        static void Write_pat(StreamWriter sw, String DataStr, String InitialStr)
        {
            bool effective_data = false;


            if (DataStr.Substring(7, 2) == "00")
                effective_data = true;//hex 文件“00”表示数据有效

            if (effective_data)
            {
                int addr = AddrStr_to_int(DataStr.Substring(3, 4)) + ExLineAddr;//获取地址2Byte

                int dataLength = DataStr_to_int(DataStr.Substring(1, 2));//需要写入数据的长度
                while (dataLength < 16)
                {
                    DataStr = DataStr.Insert(DataStr.Length - 2, "FF");
                    dataLength += 1;
                }

                long writedata = 0;
                for (int j = 0; j < dataLength; j++)
                {
                    int index = j % 4;
                    writedata += (long)(DataStr_to_int(DataStr.Substring(9 + j * 2, 2)) * (long)Math.Pow(2, index * 8));

                    if (((addr + j) % PageSize) % (PageSize - 4) == 0 && ((addr + j) % PageSize) != 0)
                    {
                        SWD_Write_Addr(sw, InitialStr, 0x41000014);
                        //SWD_Write_Fix(sw, InitialStr, WriteSize);
                        SWD_Write_Data(sw, InitialStr, 0x01080001);//置位PGSTRT
                    }

                    if (j % 4 == 0)// 每次写1word(4Byte)前，先发write 地址命令
                    {
                        SWD_Write_Addr(sw, InitialStr, addr + j + Flash_Addr);//addr
                        //SWD_Write_Fix(sw, InitialStr, WriteSize);

                    }
                    if ((j + 1) % 4 == 0)
                    {
                        SWD_Write_Data(sw, InitialStr, writedata);
                        writedata = 0;
                    }

                    addr_end_num = addr + j + 1;
                }

                if ((addr + 0x10) % PageSize == 0)
                {
                    Prog_PEdelay_test(sw, InitialStr);//每page delay一次

                }
            }

            //如果文件结束时，数据不满足1个page，则将数据补FF
            if (DataStr.Substring(7, 2) == "05" && (addr_end_num % PageSize != 0))//end
            {

                for (int j = 0; j < (PageSize - addr_end_num % PageSize); j++)
                {
                    if (((addr_end_num + j) % PageSize) % 0x1FC == 0 && ((addr_end_num + j) % PageSize) != 0)
                    {
                        SWD_Write_Addr(sw, InitialStr, 0x41000014);//addr
                        //SWD_Write_Fix(sw, InitialStr, WriteSize);//addr
                        SWD_Write_Data(sw, InitialStr, 0x01080001);
                    }

                    if (j % 4 == 0)// 每次写1word(4Byte)前，先发write 地址命令
                    {
                        SWD_Write_Addr(sw, InitialStr, addr_end_num + j + Flash_Addr);//addr
                        //SWD_Write_Fix(sw, InitialStr, WriteSize);

                    }
                    if ((j + 1) % 4 == 0)
                    {
                        SWD_Write_Data(sw, InitialStr, 0xFFFFFFFF);

                    }
                }

                Prog_PEdelay_test(sw, InitialStr);//每page delay一次
            }

        }
        static void Read_pat(StreamWriter sw, String DataStr, String InitialStr)
        {
            bool effective_data = false;

            if (DataStr.Substring(7, 2) == "00") effective_data = true;//hex 文件“00”表示数据有效


            if (effective_data)
            {

                int addr = AddrStr_to_int(DataStr.Substring(3, 4));//获取地址2Byte

                int dataLength = DataStr_to_int(DataStr.Substring(1, 2));//需要读取数据的长度
                while (dataLength < 16)
                {
                    DataStr = DataStr.Insert(DataStr.Length - 2, "FF");
                    dataLength += 1;
                }

                long readdata = 0;
                for (int j = 0; j < dataLength; j++)
                {
                    int index = j % 4;
                    readdata += (long)(DataStr_to_int(DataStr.Substring(9 + j * 2, 2)) * (long)Math.Pow(2, index * 8));

                    if (j % 4 == 0)// 每次写1word(4Byte)前，先发write 地址命令
                    {
                        SWD_Write_Addr(sw, InitialStr, addr + j + Flash_Addr);//addr
                        SWD_Read_Fix(sw, InitialStr, ReadSize);

                    }
                    if ((j + 1) % 4 == 0)
                    {
                        SWD_Read_Data(sw, InitialStr, readdata);
                        readdata = 0;
                    }
                }

            }
        }

        static public int AddrStr_to_int(string DataStr)
        {
            int bit0 = Convert.ToChar(DataStr.Substring(0, 1));
            int bit1 = Convert.ToChar(DataStr.Substring(1, 1));
            int bit2 = Convert.ToChar(DataStr.Substring(2, 1));
            int bit3 = Convert.ToChar(DataStr.Substring(3, 1));

            int length = 0;

            if (bit0 >= 65) length += (bit0 - 55) * 16 * 16 * 16;
            else length += (bit0 - 48) * 16 * 16 * 16;

            if (bit1 >= 65) length += (bit1 - 55) * 16 * 16;
            else length += (bit1 - 48) * 16 * 16;

            if (bit2 >= 65) length += (bit2 - 55) * 16;
            else length += (bit2 - 48) * 16;

            if (bit3 >= 65) length += (bit3 - 55) * 1;
            else length += (bit3 - 48) * 1;

            return length;
        }

        static public int DataStr_to_int(string DataStr)
        {
            int high_po = Convert.ToChar(DataStr.Substring(0, 1));
            int low_pol = Convert.ToChar(DataStr.Substring(1, 1));
            int length = 0;

            if (high_po >= 65) length += (high_po - 55) * 16;
            else length += (high_po - 48) * 16;

            if (low_pol >= 65) length += (low_pol - 55);
            else length += (low_pol - 48);

            return length;
        }

    }

}
