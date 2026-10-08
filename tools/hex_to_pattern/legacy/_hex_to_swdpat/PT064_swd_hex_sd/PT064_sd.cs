using System;
using System.Linq;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

namespace PT064_swd_hex_sd
{
    class PT064_sd
    {
        //淮东要的客户地址
        //public static string StilPath = @"D:\\HEX_TO_SD\\";
        //public static string StilPath_new = @"D:\\HEX_TO_SD\\";


        //public static string StilPath = @"D:\\CP_Pattern\\Start\\";
        //public static string StilPath_new = @"D:\\CP_Pattern\\sd\\";

        //public static string StilPath = @"D:\\01_Work\\CP_Map_Change\\Hex\\";
        //public static string StilPath_new = @"D:\\01_Work\\CP_Map_Change\\Pat\\";
     
        public static string StilPath = AppDomain.CurrentDomain.BaseDirectory;
        public static string StilPath_new = AppDomain.CurrentDomain.BaseDirectory;

        public static int cyc_count = 0;
        public static bool addr_first = true;
        public static int addr_end_num = 0;

        public static int Erase_delay = 3500;//T=1uS,Erase=3.5mS
        public static int Pgm_delay = 1000;//T=1uS,Pgm=1mS
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
            StreamReader sr = new StreamReader(pathSrc, Encoding.Default);
            StreamWriter sw = new StreamWriter(StilPath_new + pathDet + ".sd");

            //SCLK,SDA
            string InitialStr = "      11;";//初始字符串
            string line = "";


            Pat_header(sw, pathDet);
            SWD_Check_Start(sw);
            
            SWD_Mass_Erase(sw, InitialStr);

            SWD_Write_MER_EOPIE(sw, InitialStr);
            SWD_Write_main_anyvalue(sw, InitialStr);
            Erase_PEdelay_test(sw, InitialStr);

            SWD_Write_Addr(sw, InitialStr, 0x40022014);//addr
            SWD_Write_Fix(sw, InitialStr, 0x22000042);//addr
            SWD_Write_Data(sw, InitialStr, 0x00000001);

            //write
            while ((line = sr.ReadLine()) != null)
            {
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
            //string PatName = "SPM_PATTERN() {";
            //PatName = PatName.Insert(PatName.IndexOf("(") + 1, TxtName);
            sw.WriteLine("");
            sw.WriteLine("HEAD[PIN_NAME]: ");
            sw.WriteLine("PA2,PB6,PC0;");//SCLK,SDA,NRST
            sw.WriteLine("END_HEAD;");
            sw.WriteLine("");

            sw.WriteLine("@@PATTERN_DEFINE");

            sw.WriteLine("START:011;");
            sw.WriteLine("      111;");
            sw.WriteLine("      111;RPT 9500;");
            sw.WriteLine("      111;");
            sw.WriteLine("      111;");
        }

        static void Pat_end(StreamWriter sw)
        {
            sw.WriteLine("      101;");
            sw.WriteLine("      101;RPT 53;");
            sw.WriteLine("      101;");
            sw.WriteLine("  END:011;");
            sw.WriteLine("@@END_PATTERN_DEFINE");
        }

        static void SWD_Check_Start(StreamWriter sw)
        {
            sw.WriteLine("      111;RPT 2;");
            sw.WriteLine("      101;RPT 2;");
            sw.WriteLine("      111;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;");
            sw.WriteLine("      101;RPT 2;");
            sw.WriteLine("      111;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;RPT 2;");
            sw.WriteLine("      1H1;RPT 3;");
            sw.WriteLine("      1L1;");
            sw.WriteLine("      1H1;RPT 3;");
            sw.WriteLine("      1L1;RPT 3;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;RPT 3;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;RPT 5;");
            sw.WriteLine("      1H1;RPT 4;");
            sw.WriteLine("      1L1;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;RPT 5;");
            sw.WriteLine("      1X1;");
            sw.WriteLine("      101;");
            sw.WriteLine("      101;RPT 40;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;");
            sw.WriteLine("      101;RPT 2;");
            sw.WriteLine("      111;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;RPT 2;");
            sw.WriteLine("      1X1;");
            sw.WriteLine("      101;RPT 29;");
            sw.WriteLine("      111;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;");
            sw.WriteLine("      101;RPT 55;");
            sw.WriteLine("      111;");
            sw.WriteLine("      101;RPT 3;");
            sw.WriteLine("      111;RPT 2;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;RPT 2;");
            sw.WriteLine("      1X1;");
            sw.WriteLine("      101;RPT 87;");
        }

        //置位FLASH_CR寄存器的MER位和EOPIE位
        static void SWD_Write_MER_EOPIE(StreamWriter sw, String InitialStr)
        {
            SWD_Write_Addr(sw, InitialStr, 0x40022014);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0x01000004);//mass erase
        }

        static void SWD_Write_main_anyvalue(StreamWriter sw, String InitialStr)
        {
            SWD_Write_Addr(sw, InitialStr, 0x08000000);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0x12345678);
        }

        static void SWD_Mass_Erase(StreamWriter sw, String InitialStr)
        {
            

            SWD_Write_Addr(sw, InitialStr, 0xE000EDF0);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0xA05F0003);

            //key1
            SWD_Write_Addr(sw, InitialStr, 0x40022008);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0x45670123);
            //key2
            SWD_Write_Addr(sw, InitialStr, 0x40022008);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0xCDEF89AB);

            //加载24MHz Param信息
            SWD_Write_Addr(sw, InitialStr, 0x40022100);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0x000000B4);

            SWD_Write_Addr(sw, InitialStr, 0x40022104);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0x000001B0);

            SWD_Write_Addr(sw, InitialStr, 0x40022108);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0x000000B4);

            SWD_Write_Addr(sw, InitialStr, 0x4002210C);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0x000006C0);

            SWD_Write_Addr(sw, InitialStr, 0x40022110);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0x000000B4);

            SWD_Write_Addr(sw, InitialStr, 0x40022114);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0x00014820);

            SWD_Write_Addr(sw, InitialStr, 0x40022118);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0x00014820);

            SWD_Write_Addr(sw, InitialStr, 0x4002211C);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0x00005DC0);

            SWD_Write_Addr(sw, InitialStr, 0x40022120);
            SWD_Write_Fix(sw, InitialStr, 0x22000042);
            SWD_Write_Data(sw, InitialStr, 0x000012C0);

        }

        static void SWD_Write_Addr(StreamWriter sw, String InitialStr, long addr)
        {
            sw.WriteLine("      111;RPT 2;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;");
            sw.WriteLine("      101;RPT 3;");
            sw.WriteLine("      111;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;RPT 2;");
            sw.WriteLine("      1X1;");
            sw.WriteLine("      101;");

            string AddrStr = Convert.ToString(addr, 2).PadLeft(32, '0');//将int类型的值转换为32bit长度的字符串
            AddrStr = new string(AddrStr.ToCharArray().Reverse().ToArray());//倒转字符串
            string AddrStr_rep = AddrStr.Replace("1", "");
            int Parity_bit = 0;
            if ((AddrStr.Length - AddrStr_rep.Length) % 2 != 0) Parity_bit = 1;//判断奇偶校验码的值

            for (int i = 0; i < AddrStr.Length; i++)
            {
                if (i == 0)
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("1") + 1, AddrStr.Substring(i, 1)) + "//" + string.Format("{0:x8}", addr));
                else
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("1") + 1, AddrStr.Substring(i, 1)));
            }
            sw.WriteLine("      1" + Parity_bit.ToString() + "1;");
            sw.WriteLine("      101;RPT 3;");
        }


        static void SWD_Write_Fix(StreamWriter sw, String InitialStr, long addr)
        {
            sw.WriteLine("      111;RPT 2;");
            sw.WriteLine("      101;RPT 3;");
            sw.WriteLine("      111;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;RPT 2;");
            sw.WriteLine("      1X1;");
            sw.WriteLine("      101;");

            string AddrStr = Convert.ToString(addr, 2).PadLeft(32, '0');//将int类型的值转换为32bit长度的字符串
            AddrStr = new string(AddrStr.ToCharArray().Reverse().ToArray());//倒转字符串
            string AddrStr_rep = AddrStr.Replace("1", "");
            int Parity_bit = 0;
            if ((AddrStr.Length - AddrStr_rep.Length) % 2 != 0) Parity_bit = 1;//判断奇偶校验码的值

            for (int i = 0; i < AddrStr.Length; i++)
            {
                if (i == 0)
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("1") + 1, AddrStr.Substring(i, 1)) + "//" + string.Format("{0:x8}", addr));
                else
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("1") + 1, AddrStr.Substring(i, 1)));
            }
            sw.WriteLine("      1" + Parity_bit.ToString() + "1;");
            sw.WriteLine("      101;RPT 3;");
        }



        static void SWD_Write_Data(StreamWriter sw, String InitialStr, long data)
        {
            sw.WriteLine("      111;RPT 2;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;RPT 3;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;RPT 2;");
            sw.WriteLine("      1X1;");
            sw.WriteLine("      101;");

            string DataStr = Convert.ToString(data, 2).PadLeft(32, '0');//将int类型的值转换为32bit长度的字符串
            DataStr = new string(DataStr.ToCharArray().Reverse().ToArray());//倒转字符串

            string DataStr_rep = DataStr.Replace("1", "");
            int Parity_bit = 0;
            if ((DataStr.Length - DataStr_rep.Length) % 2 != 0) Parity_bit = 1;//判断奇偶校验码的值

            for (int i = 0; i < DataStr.Length; i++)
            {
                if (i == 0)
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("1") + 1, DataStr.Substring(i, 1)) + "//" + string.Format("{0:x8}", data));
                else
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("1") + 1, DataStr.Substring(i, 1)));
            }
            sw.WriteLine("      1" + Parity_bit.ToString() + "1;");
            sw.WriteLine("      101;RPT 53;");
        }


        static void SWD_Read_Fix(StreamWriter sw, String InitialStr, long addr)
        {
            sw.WriteLine("      111;RPT 2;");
            sw.WriteLine("      101;RPT 3;");
            sw.WriteLine("      111;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;RPT 2;");
            sw.WriteLine("      1X1;");
            sw.WriteLine("      101;");

            string AddrStr = Convert.ToString(addr, 2).PadLeft(32, '0');//将int类型的值转换为32bit长度的字符串
            AddrStr = new string(AddrStr.ToCharArray().Reverse().ToArray());//倒转字符串
            string AddrStr_rep = AddrStr.Replace("1", "");
            int Parity_bit = 0;
            if ((AddrStr.Length - AddrStr_rep.Length) % 2 != 0) Parity_bit = 1;//判断奇偶校验码的值

            for (int i = 0; i < AddrStr.Length; i++)
            {
                if (i == 0)
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("1") + 1, AddrStr.Substring(i, 1)) + "//" + string.Format("{0:x8}", addr));
                else
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("1") + 1, AddrStr.Substring(i, 1)));
            }
            sw.WriteLine("      1" + Parity_bit.ToString() + "1;");
            sw.WriteLine("      101;RPT 3;");

            sw.WriteLine("      111;RPT 5;");
            sw.WriteLine("      101;RPT 2;");
            sw.WriteLine("      111;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;RPT 35;");
            sw.WriteLine("      1X1;");
            sw.WriteLine("      101;RPT 2;");
        }

        static void SWD_Read_Data(StreamWriter sw, String InitialStr, long data)
        {
            sw.WriteLine("      111;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;RPT 4;");
            sw.WriteLine("      101;");
            sw.WriteLine("      111;");
            sw.WriteLine("      1H1;");
            sw.WriteLine("      1L1;RPT 2;");

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
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("1") + 1, DataStr.Substring(i, 1)) + "//" + string.Format("{0:x8}", data));
                else
                    sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("1") + 1, DataStr.Substring(i, 1)));
            }
            sw.WriteLine("      1" + Parity_bit.ToString().Replace('1', 'H').Replace('0', 'L') + "1;");
            sw.WriteLine("      1X1;");
            sw.WriteLine("      101;RPT 52;");
        }


        static void Erase_Delay_pt061(StreamWriter sw)
        {

            sw.WriteLine("      101;");
            sw.WriteLine("      101;");//sw.WriteLine("      111*TS51;");
            sw.WriteLine("      101;");
            sw.WriteLine("      101;RPT " + (Erase_delay+600).ToString() + ";");
            sw.WriteLine("      101;");
            sw.WriteLine("      101;");//sw.WriteLine("      111*TS11;");
            sw.WriteLine("      101;");
        }

        static void Prog_Delay_pt061(StreamWriter sw)
        {
            sw.WriteLine("      101;");
            sw.WriteLine("      101;");//sw.WriteLine("      111*TS61;");
            sw.WriteLine("      101;");
            sw.WriteLine("      101;RPT " + (Pgm_delay+100).ToString() + ";");
            sw.WriteLine("      101;");
            sw.WriteLine("      101;");//sw.WriteLine("      111*TS11;");
            sw.WriteLine("      101;");
        }

        static void Prog_PEdelay_test(StreamWriter sw, String InitialStr)
        {

            Prog_Delay_pt061(sw);

            SWD_Write_Addr(sw, InitialStr, 0x40022010);//addr,置位FLASH_SR寄存器EOP位和BSY位
            SWD_Write_Fix(sw, InitialStr, 0x22000042);//addr
            SWD_Write_Data(sw, InitialStr, 0x00000001);

        }

        static void Erase_PEdelay_test(StreamWriter sw, String InitialStr)
        {

            Erase_Delay_pt061(sw);

            SWD_Write_Addr(sw, InitialStr, 0x40022010);//addr,置位FLASH_SR寄存器EOP位和BSY位
            SWD_Write_Fix(sw, InitialStr, 0x22000042);//addr
            SWD_Write_Data(sw, InitialStr, 0x00000001);

        }



        static void Write_pat(StreamWriter sw, String DataStr, String InitialStr)
        {
            bool effective_data = false;


            if (DataStr.Substring(7, 2) == "00")
                effective_data = true;//hex 文件“00”表示数据有效

            if (effective_data)
            {
                int addr = AddrStr_to_int(DataStr.Substring(3, 4));//获取地址2Byte

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

                    if (((addr + j) % 0x80) % 0x7C == 0 && ((addr + j) % 0x80) != 0)
                    {
                        SWD_Write_Addr(sw, InitialStr, 0x40022014);//addr
                        SWD_Write_Fix(sw, InitialStr, 0x22000042);//addr
                        SWD_Write_Data(sw, InitialStr, 0x01080001);
                    }

                    if (j % 4 == 0)// 每次写1word(4Byte)前，先发write 地址命令
                    {
                        SWD_Write_Addr(sw, InitialStr, addr + j + 0x08000000);//addr
                        SWD_Write_Fix(sw, InitialStr, 0x22000042);

                    }
                    if ((j + 1) % 4 == 0)
                    {
                        SWD_Write_Data(sw, InitialStr, writedata);
                        writedata = 0;
                    }

                    addr_end_num = addr + j + 1;
                }

                if ((addr + 0x10) % 128 == 0) Prog_PEdelay_test(sw, InitialStr);//每page delay一次

            }

            //如果文件结束时，数据不满足1个page，则将数据补FF
            if (DataStr.Substring(7, 2) == "05" && (addr_end_num % 0x80 != 0))//end
            {

                for (int j = 0; j < (0x80 - addr_end_num % 0x80); j++)
                {
                    if (((addr_end_num + j) % 0x80) % 0x7C == 0 && ((addr_end_num + j) % 0x80) != 0)
                    {
                        SWD_Write_Addr(sw, InitialStr, 0x40022014);//addr
                        SWD_Write_Fix(sw, InitialStr, 0x22000042);//addr
                        SWD_Write_Data(sw, InitialStr, 0x01080001);
                    }

                    if (j % 4 == 0)// 每次写1word(4Byte)前，先发write 地址命令
                    {
                        SWD_Write_Addr(sw, InitialStr, addr_end_num + j + 0x08000000);//addr
                        SWD_Write_Fix(sw, InitialStr, 0x22000042);

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
                        SWD_Write_Addr(sw, InitialStr, addr + j + 0x08000000);//addr
                        SWD_Read_Fix(sw, InitialStr, 0x20000042);

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
